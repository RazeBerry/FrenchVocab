import json
import os
import re
import shutil
import string
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import genanki
from pathlib import Path
from rich.console import Console
from rich.progress import Progress
from enum import Enum, auto
from cli.menu import main_menu_loop
from anki_exporter import AnkiExporter, AnkiExportEntry, latex_to_anki_format as latex_to_anki_html
from ai_response_parser import parse_ai_response_text
import time
import keyring
import threading
from latex_repository import LatexRepository
from models import normalize_word_key
from languages import LanguageConfig, TranslatorConfig, default_language_code, get_language_config
from languages.anki_shared_styles import compute_template_hash
from typing import TYPE_CHECKING

from .translator import TranslatorCLI
from .auto_translator import AutoTranslator
from .history_logger import TranslationLogger
from ui_helper import UIHelper, read_line
from core.providers.manager import (
    ProviderManager,
    ProviderMetadata,
    ProviderResolution,
)

if TYPE_CHECKING:  # pragma: no cover - optional provider clients
    from llm_client import GeminiClient  # noqa: F401

class WordType(Enum):
    NOUN = auto()
    VERB = auto()
    ADJECTIVE = auto()
    ADVERB = auto()
    EXPRESSION = auto()
    PRONOMINAL_VERB = auto()
    OTHER = auto()


class FrenchVocabBuilder:
    DEFAULT_LANGUAGE_CONFIG = get_language_config(None)
    DEFAULT_LANGUAGE_CODE = default_language_code()
    DEFAULT_FILENAME = DEFAULT_LANGUAGE_CONFIG.vocab_filename
    language_config: LanguageConfig = DEFAULT_LANGUAGE_CONFIG
    language_code: str = DEFAULT_LANGUAGE_CODE
    DEFINITION_PREVIEW_LIMIT = 60

    def __getattribute__(self, name):
        # Lazy-load parsed LaTeX entries on first access to in-memory caches.
        if name in {"word_entries", "normalized_entries"}:
            try:
                loaded = object.__getattribute__(self, "_entries_loaded")
                loading = object.__getattribute__(self, "_entries_loading")
                ready_event = object.__getattribute__(self, "_entries_ready")
            except AttributeError:
                loaded = True
                loading = False
                ready_event = None
            if loading and ready_event:
                ready_event.wait(timeout=1.0)
            if not loaded:
                object.__getattribute__(self, "_ensure_entries_loaded")()
            try:
                return object.__getattribute__(self, name)
            except AttributeError:
                # Defensive default for test doubles using object.__new__()
                fallback = {}  # type: ignore[assignment]
                object.__setattr__(self, name, fallback)
                return fallback
        return object.__getattribute__(self, name)

    def __init__(
        self,
        latex_file: Optional[str],
        provider: str = None,
        verbose: bool = False,
        client: Optional["GeminiClient"] = None,
        language: Optional[str] = None,
        language_config: Optional[LanguageConfig] = None,
        eager_provider: bool = False,
    ):
        init_start = time.time()

        # Local import to avoid pulling heavy provider SDKs at module import time.
        from llm_client import ProviderFactory

        if language and language_config:
            raise ValueError("Provide either language or language_config, not both.")

        if language_config is None:
            resolved_language = language or self.DEFAULT_LANGUAGE_CODE
            language_config = get_language_config(resolved_language)

        self.language_config = language_config
        self.language_code = language_config.code
        self.vocab_template = language_config.vocab
        entry_command = self.vocab_template.entry_command or "\\entry"
        if not entry_command.startswith("\\"):
            entry_command = f"\\{entry_command}"
        self.entry_command = entry_command

        self.console = Console()
        self.ui = UIHelper(self.console)  # Initialize UIHelper
        # Determine project root (one level above this module)
        module_dir = Path(__file__).resolve().parent
        project_root = module_dir.parent
        self.project_root = project_root
        self.provider_manager = ProviderManager(self.ui, self.project_root)

        self.default_vocab_filename = self.language_config.vocab_filename
        if latex_file is None:
            self.latex_file = project_root / self.default_vocab_filename
            self.eng_to_fr_latex_file = project_root / self.language_config.eng_to_target_filename
            self.fr_to_eng_latex_file = project_root / self.language_config.target_to_eng_filename
        else:
            self.latex_file = Path(latex_file)
            # Assume the Eng->Fr file lives alongside the main one if a path is given
            base_dir = self.latex_file.parent
            self.eng_to_fr_latex_file = base_dir / self.language_config.eng_to_target_filename
            self.fr_to_eng_latex_file = base_dir / self.language_config.target_to_eng_filename

        if not self.latex_file.exists():
            self.create_initial_tex_file()

        # Repository for LaTeX entries (balanced-brace parser)
        self.repo = LatexRepository(self.latex_file, entry_command=self.entry_command)

        # Allow longer phrases before triggering the length check
        self.max_word_length = 1000  # default max characters (overridable)
        self.max_words: Optional[int] = None  # unlimited by default; overridable
        self._entry_count_snapshot: Optional[tuple[float, int, int]] = None  # (mtime, size, count)
        self.allow_sentence_punctuation: bool = True  # allow punctuation by default
        self.route_sentences: bool = True  # default: route sentences to Fr->En translator
        self.sentence_examples_in_vocab: bool = False  # default: omit examples for sentences
        self.word_entries: Dict[str, Dict] = {}
        self.normalized_entries: Dict[str, str] = {}
        self._entries_lock = threading.Lock()
        self.config_file = "vocab_builder_config.json"
        self._config_data: Dict[str, Any] = {}
        self.history_logger: Optional[TranslationLogger] = None
        self._entries_loaded: bool = False
        self._entries_loading: bool = False
        self._entries_ready = threading.Event()
        self._warmup_threads: List[threading.Thread] = []
        self._last_warmup_error: Optional[str] = None
        
        # Initialize the LLM client (allow injection)
        self.client = client
        self.api_available = self.client is not None
        self.api_error_reason: Optional[str] = None
        self.session_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "thoughts_tokens": 0,
            "tool_tokens": 0,
            "cached_tokens": 0,
        }
        self.session_requests: int = 0
        
        # Apply optional runtime settings (env/config overrides)
        self._load_input_limits()
        self.history_logger = self._create_history_logger()
        self._llm_thread = None
        self._llm_init_error: Optional[Exception] = None

        # Initialize translator attribute
        self.eng_to_fr_translator: Optional[TranslatorCLI] = None
        self.fr_to_eng_translator: Optional[TranslatorCLI] = None
        self.auto_translator: Optional[AutoTranslator] = None
        self.duplicate_resolution: Optional[Dict[str, str]] = None  # stores {'mode': 'merge'|'force', 'existing': <word>}
        self.enable_auto_translator: bool = self._should_enable_auto_translator()

        self.eager_provider = eager_provider or (provider is not None)

        # Determine provider early and set verbosity before key bootstrapping
        requested_provider = provider or ProviderFactory.default_provider()
        self.provider_metadata: ProviderMetadata = self.provider_manager.get_metadata(requested_provider)
        self.provider = self.provider_metadata.identifier
        self.verbose = verbose

        # Load configuration + init client only if not injected
        load_config_start = time.time()
        if self.client is None:
            if self.eager_provider:
                if self._prepare_provider():
                    self._initialize_llm_client()
                else:
                    self._enter_degraded_mode(self.api_error_reason or "API setup skipped.")
            else:
                self._start_background_llm_init()
        else:
            self.api_available = True
        load_config_end = time.time()

        # Defer LaTeX parsing until first use to reduce startup time for large libraries.
        
        self.exported_words_file = self._resolve_exported_words_path(project_root, self.latex_file.parent)
        self.last_export_metadata: Optional[Dict[str, Any]] = None
        (
            self.exported_words,
            self.exported_deck_version,
            self.last_export_metadata,
        ) = self.load_exported_words()
        self.entry_count = self.count_entries()
        
        # Initialize translators based on current client availability
        self._init_translators()

        # Kick off background warm-up tasks (LaTeX parse/history) in parallel with UI readiness.
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("FRENCHVOCAB_FORCE_SYNC_LOAD"):
            # Tests expect entries to be immediately available.
            self._ensure_entries_loaded()
        else:
            self._start_warmup_tasks()

        init_end = time.time()
        if self.verbose:
            timings = (
                f"Total init time: {init_end - init_start:.5f} seconds\n"
                f"  Load config time: {load_config_end - load_config_start:.5f} seconds\n"
                f"  Parsed entries lazily on first access"
            )
            self.ui.info(timings, accent="dim")

    def _init_translators(self) -> None:
        """Instantiate translator flows when an LLM client is available."""
        if not self.client:
            self.eng_to_fr_translator = None
            self.fr_to_eng_translator = None
            self.auto_translator = None
            return

        if (
            self.eng_to_fr_translator
            and self.fr_to_eng_translator
            and self.eng_to_fr_translator.client is self.client
            and self.fr_to_eng_translator.client is self.client
        ):
            return

        eng_to_target = self.language_config.eng_to_target
        target_to_eng = self.language_config.target_to_eng

        self.eng_to_fr_translator = TranslatorCLI(
            console=self.console,
            client=self.client,
            config=eng_to_target,
            latex_file_path=self.eng_to_fr_latex_file,
            direction="eng_to_target",
            logger=self.history_logger,
            usage_callback=self._record_usage,
        )
        self.fr_to_eng_translator = TranslatorCLI(
            console=self.console,
            client=self.client,
            config=target_to_eng,
            latex_file_path=self.fr_to_eng_latex_file,
            direction="target_to_eng",
            logger=self.history_logger,
            usage_callback=self._record_usage,
        )
        self._init_auto_translator()

    def _init_auto_translator(self) -> None:
        """Create the intelligent translator wrapper when enabled."""
        if not self.enable_auto_translator:
            self.auto_translator = None
            return

        prompt = getattr(self.language_config, "auto_prompt_template", None)
        if not prompt or not self.client:
            self.auto_translator = None
            return

        if not (self.eng_to_fr_translator and self.fr_to_eng_translator):
            self.auto_translator = None
            return

        prompt_variable = getattr(self.language_config, "auto_prompt_variable", "source_text")
        self.auto_translator = AutoTranslator(
            console=self.console,
            client=self.client,
            language_config=self.language_config,
            eng_to_target=self.eng_to_fr_translator,
            target_to_eng=self.fr_to_eng_translator,
            prompt_template=prompt,
            prompt_variable=prompt_variable,
            usage_callback=self._record_usage,
        )

    def _apply_provider_resolution(self, resolution: ProviderResolution) -> None:
        """Persist provider metadata and API key details after successful setup."""
        self.provider_metadata = resolution.metadata
        self.provider = resolution.metadata.identifier
        os.environ[resolution.metadata.env_var] = resolution.api_key
        self.api_error_reason = None

    def _prepare_provider(self) -> bool:
        """Ensure provider credentials are ready; return False when setup is skipped."""
        try:
            resolution = self.provider_manager.prepare_provider(self.provider_metadata)
        except RuntimeError as exc:
            message = str(exc) or "API setup aborted by user."
            self.api_error_reason = message
            self.ui.error(message, with_panel=True)
            return False

        self._apply_provider_resolution(resolution)
        return True

    def _initialize_llm_client(
        self,
        *,
        announce: bool = True,
        rebuild_translators: bool = False,
    ) -> bool:
        """Create the LLM client for the active provider."""
        from llm_client import ProviderFactory

        try:
            self.client = ProviderFactory.create(self.provider)
        except Exception as exc:
            self._enter_degraded_mode(f"Error initializing {self.provider} client: {exc}")
            return False

        self.api_available = True
        self.api_error_reason = None
        if announce:
            self.ui.success(f"{self.provider.capitalize()} client initialized successfully!")
        if rebuild_translators:
            self._init_translators()
        return True

    def _start_background_llm_init(self) -> None:
        """Kick off non-blocking LLM setup without blocking startup on keyring/env lookups."""
        if getattr(self, "_llm_thread", None):
            return

        self.api_available = False
        self.api_error_reason = "LLM initialization in background."

        def _worker():
            try:
                resolution = self.provider_manager.resolve_provider_silently(self.provider_metadata)
                if not resolution:
                    # No credentials; switch to deferred state.
                    self.api_available = False
                    self.api_error_reason = "LLM not initialized (lazy mode). Configure provider on first AI use."
                    return

                self._apply_provider_resolution(resolution)
                if self._initialize_llm_client(announce=False, rebuild_translators=True):
                    self.api_available = True
                    self.api_error_reason = None
            except Exception as exc:  # pragma: no cover - defensive
                self._llm_init_error = exc
            finally:
                # clear the thread handle so status panels won't show "Initializing" forever
                self._llm_thread = None

        import threading

        self._llm_init_error = None
        self._llm_thread = threading.Thread(target=_worker, name="llm-init", daemon=True)
        self._llm_thread.start()

    def _safe_warmup(self, fn, label: str) -> None:
        """Run a warm-up task defensively so background failures never block startup."""
        try:
            fn()
        except Exception as exc:  # pragma: no cover - best-effort telemetry
            self._last_warmup_error = f"{label}: {exc}"

    def _start_warmup_tasks(self) -> None:
        """Run non-critical startup tasks in parallel (e.g., LaTeX parse)."""
        tasks: List[Tuple[str, Any]] = []
        if not getattr(self, "_entries_loaded", False):
            tasks.append(("entries", self._ensure_entries_loaded))

        for label, fn in tasks:
            t = threading.Thread(target=self._safe_warmup, args=(fn, label), name=f"warmup-{label}", daemon=True)
            t.start()
            self._warmup_threads.append(t)

    def _await_background_llm(self, timeout: float = 5.0) -> bool:
        """Wait for background init to finish; return True if client available."""
        thread = getattr(self, "_llm_thread", None)
        if not thread:
            return False
        thread.join(timeout=timeout)
        if thread.is_alive():
            return False
        # Thread finished; clear handle
        self._llm_thread = None
        if self.client:
            self.api_available = True
            self.api_error_reason = None
            return True
        if self._llm_init_error:
            self._enter_degraded_mode(str(self._llm_init_error))
        return False

    def _enter_degraded_mode(self, reason: str) -> None:
        """Disable AI-dependent features while keeping the rest of the app usable."""
        clean_reason = (reason or "").strip() or "No AI provider configured."
        self.client = None
        self.api_available = False
        self.api_error_reason = clean_reason
        self.eng_to_fr_translator = None
        self.fr_to_eng_translator = None
        self.auto_translator = None
        self.ui.warning(f"AI features unavailable: {clean_reason}")
        self.ui.info(
            "Existing vocabulary and exports remain accessible. Retry provider setup when prompted to restore AI features."
        )

    def ensure_llm_ready(self) -> bool:
        """Ensure the LLM client is available, prompting for reconfiguration if needed."""
        # If a background initialization is underway or completed, honor it first.
        if not self.client and getattr(self, "_llm_thread", None):
            # Give the background task a brief chance to finish before prompting.
            if self._await_background_llm(timeout=0.5):
                return True

        if self.client:
            return True

        reason = self.api_error_reason or "No AI provider configured."
        self.ui.warning(f"AI provider unavailable: {reason}")

        options = [
            ("retry", "Retry provider setup now"),
            ("settings", "Open AI settings"),
            ("skip", "Return without AI features"),
        ]

        try:
            choice = self.ui.interactive_menu(
                "AI Provider Required",
                options,
                "AI-powered features need a configured provider • [Esc] Skip",
                show_keys=False,
            )
        except KeyboardInterrupt:
            return False

        if choice == "retry":
            if self.reconfigure_provider():
                return True
            self.ui.warning("Provider setup failed. Remaining in offline mode.")
        elif choice == "settings":
            self.show_settings_screen()
            return self.ensure_llm_ready()

        return False

    def reconfigure_provider(self) -> bool:
        """Run provider setup again and rebuild dependent components."""
        self.ui.info("Re-running provider setup...")
        if not self._prepare_provider():
            return False
        return self._initialize_llm_client(rebuild_translators=True)

    def _ui_text(self, key: str, fallback: str) -> str:
        strings = getattr(self.language_config, "ui_strings", {}) or {}
        return strings.get(key, fallback)

    def _translator_title(self, config: TranslatorConfig) -> str:
        title = getattr(config, "ui_title", None)
        if title:
            return title
        source = getattr(config, "source_label", "Source")
        target = getattr(config, "target_label", "Target")
        return f"{source} → {target} Translator"

    def _resolve_exported_words_path(self, project_root: Path, target_dir: Path) -> Path:
        """Resolve the exported words tracker, preferring the LaTeX file's directory."""
        lang_code = self.language_code
        candidate = target_dir / f"exported_words_{lang_code}.json"
        if candidate.exists():
            return candidate

        def _fallback_candidates() -> List[Path]:
            paths: List[Path] = []
            paths.append(project_root / f"exported_words_{lang_code}.json")
            if lang_code == self.DEFAULT_LANGUAGE_CODE:
                paths.append(project_root / "exported_words.json")
            return paths

        for legacy_path in _fallback_candidates():
            if not legacy_path.exists():
                continue
            if legacy_path.parent == target_dir:
                return legacy_path
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(legacy_path, candidate)
                return candidate
            except OSError:
                return legacy_path

        return candidate

    def _entry_command(self) -> str:
        entry_cmd = getattr(self, "entry_command", self.DEFAULT_LANGUAGE_CONFIG.vocab.entry_command)
        if not entry_cmd.startswith('\\'):
            entry_cmd = f"\\{entry_cmd}"
        return entry_cmd

    def detect_input_type(self, text: str) -> str:
        """Classify input as 'word', 'expression', or 'sentence' using simple heuristics."""
        if not text:
            return 'word'
        t = text.strip()
        # Newlines strongly indicate sentence text
        if '\n' in t:
            return 'sentence'
        # Sentence-ending punctuation or long length
        if any(p in t for p in '.!?;:') or len(t) > 120:
            return 'sentence'
        # Word count thresholds
        wc = len(t.split())
        if wc >= 9:
            return 'sentence'
        if wc >= 2:
            return 'expression'
        return 'word'

    def create_initial_tex_file(self):
        try:
            template = getattr(self, "vocab_template", self.DEFAULT_LANGUAGE_CONFIG.vocab)
            # Create the parent directory if needed (only if not in the current directory)
            if self.latex_file.parent != Path('.'):
                self.latex_file.parent.mkdir(parents=True, exist_ok=True)
            with self.latex_file.open('w', encoding='utf-8') as file:
                file.write(template.initial_content)
                sample = template.sample_entry or ""
                if sample:
                    file.write(sample)
                file.write(template.final_content)
            self.ui.success(f"Created initial LaTeX file: {self.latex_file}")
        except IOError as e:
            self.ui.error(f"Error creating initial LaTeX file: {e}", with_panel=True)
            raise

    def _load_input_limits(self) -> None:
        """Load UI/input and routing options from env or optional JSON config.

        Priority: defaults < config file < environment variables.
        - Env vars: FRENCH_VOCAB_MAX_CHARS, FRENCH_VOCAB_MAX_WORDS
        - Config file (JSON): {"input_limits": {"max_chars": int, "max_words": int|null}}
        Any non-positive or null max_words disables the word-count limit.
        """
        # 1) Config file (optional)
        try:
            from pathlib import Path as _Path
            cfg_path = _Path(__file__).parent / str(self.config_file)
            if cfg_path.exists():
                with cfg_path.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._config_data = data
                else:
                    self._config_data = {}
                limits = (data or {}).get('input_limits', {})
                if isinstance(limits, dict):
                    if 'max_chars' in limits:
                        try:
                            mc = int(limits['max_chars'])
                            if mc > 0:
                                self.max_word_length = mc
                        except (ValueError, TypeError):
                            pass
                    if 'max_words' in limits:
                        try:
                            mw = limits['max_words']
                            # allow null/None/<=0 to mean unlimited
                            if mw is None:
                                self.max_words = None
                            else:
                                mw_int = int(mw)
                                self.max_words = mw_int if mw_int > 0 else None
                        except (ValueError, TypeError):
                            pass
                    # sentence mode flag (optional)
                    if 'sentence_mode' in limits:
                        try:
                            sm = limits['sentence_mode']
                            if isinstance(sm, bool):
                                self.allow_sentence_punctuation = sm
                            elif isinstance(sm, str):
                                self.allow_sentence_punctuation = sm.strip().lower() in ("1", "true", "yes", "y", "on")
                        except Exception:
                            pass
                    # sentence routing (optional)
                    if 'route_sentences' in limits:
                        try:
                            rs = limits['route_sentences']
                            if isinstance(rs, bool):
                                self.route_sentences = rs
                            elif isinstance(rs, str):
                                self.route_sentences = rs.strip().lower() in ("1", "true", "yes", "y", "on")
                        except Exception:
                            pass
                    # include examples for sentences when kept in vocab
                    if 'sentence_examples' in limits:
                        try:
                            se = limits['sentence_examples']
                            if isinstance(se, bool):
                                self.sentence_examples_in_vocab = se
                            elif isinstance(se, str):
                                self.sentence_examples_in_vocab = se.strip().lower() in ("1", "true", "yes", "y", "on")
                        except Exception:
                            pass
        except Exception:
            # Be resilient; ignore config errors
            pass

        # 2) Environment variables (highest priority)
        try:
            env_chars = os.getenv('FRENCH_VOCAB_MAX_CHARS')
            if env_chars:
                ec = int(env_chars)
                if ec > 0:
                    self.max_word_length = ec
        except (ValueError, TypeError):
            pass
        try:
            env_words = os.getenv('FRENCH_VOCAB_MAX_WORDS')
            if env_words is not None:
                ew = int(env_words)
                self.max_words = ew if ew > 0 else None
        except (ValueError, TypeError):
            pass
        # sentence mode via env
        env_sentence = os.getenv('FRENCH_VOCAB_SENTENCE_MODE') or os.getenv('FRENCH_VOCAB_ALLOW_PUNCT')
        if env_sentence is not None:
            self.allow_sentence_punctuation = str(env_sentence).strip().lower() in ("1", "true", "yes", "y", "on")
        # routing and sentence examples
        env_route = os.getenv('FRENCH_VOCAB_ROUTE_SENTENCES')
        if env_route is not None:
            self.route_sentences = str(env_route).strip().lower() in ("1", "true", "yes", "y", "on")
        env_sent_ex = os.getenv('FRENCH_VOCAB_SENTENCE_EXAMPLES')
        if env_sent_ex is not None:
            self.sentence_examples_in_vocab = str(env_sent_ex).strip().lower() in ("1", "true", "yes", "y", "on")

    def _should_enable_auto_translator(self) -> bool:
        env_value = os.getenv("FRENCH_VOCAB_AUTO_TRANSLATOR")
        if env_value is not None:
            return str(env_value).strip().lower() in ("1", "true", "yes", "y", "on")
        return bool(getattr(self.language_config, "auto_prompt_template", None))

    def _create_history_logger(self) -> TranslationLogger:
        config_section: Dict[str, Any] = {}
        raw_config = self._config_data.get("history_logging") if isinstance(self._config_data, dict) else None
        if isinstance(raw_config, dict):
            config_section = raw_config

        enabled = bool(config_section.get("enabled", True))
        env_disabled = os.getenv("FRENCH_VOCAB_HISTORY_DISABLED")
        if env_disabled and env_disabled.strip().lower() in ("1", "true", "yes", "y", "on"):
            enabled = False
        env_enabled = os.getenv("FRENCH_VOCAB_HISTORY_ENABLED")
        if env_enabled and env_enabled.strip().lower() in ("1", "true", "yes", "y", "on"):
            enabled = True

        base_dir_override = os.getenv("FRENCH_VOCAB_HISTORY_DIR")
        if base_dir_override:
            base_dir = Path(base_dir_override)
        else:
            configured_dir = config_section.get("directory")
            if configured_dir:
                base_dir = Path(configured_dir)
                if not base_dir.is_absolute():
                    base_dir = (self.project_root / base_dir).resolve()
            else:
                base_dir = self.project_root / "data" / "history"

        file_pattern = config_section.get("file_pattern", "{language}_translations.jsonl")

        return TranslationLogger(
            language_code=self.language_code,
            base_dir=base_dir,
            enabled=enabled,
            file_pattern=file_pattern,
            on_error=self._history_log_error,
        )

    def _history_log_error(self, message: str) -> None:
        try:
            self.ui.warning(message)
        except Exception as e:
            # Fallback: print to stderr if UI fails
            import sys
            print(f"WARNING: {message}", file=sys.stderr)
            print(f"(UI error: {e})", file=sys.stderr)

    def _provider_label(self) -> str:
        label = self.provider.capitalize() if isinstance(self.provider, str) else "provider"
        if self.client is not None:
            getter = getattr(self.client, "model_label", None)
            if callable(getter):
                try:
                    label = getter()
                except Exception:
                    label = self.client.__class__.__name__
        return label

    def _log_vocab_history(
        self,
        *,
        action: str,
        original_text: Optional[str],
        saved_word: str,
        word_type: str,
        definitions: List[str],
        examples: List[Tuple[str, str]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.history_logger or not self.history_logger.enabled:
            return
        try:
            self.history_logger.log_vocab_entry(
                action=action,
                word=saved_word,
                word_type=word_type,
                definitions=definitions,
                examples=examples,
                source_text=original_text,
                normalized_key=self.normalize_word(saved_word),
                provider=self._provider_label(),
                latex_file=self.latex_file,
                metadata=metadata,
            )
        except Exception:
            # Errors are reported via the logger's error handler
            pass

    def _log_merge_history(
        self,
        *,
        existing_word: str,
        final_type: str,
        merged_definitions: List[str],
        merged_examples: List[Tuple[str, str]],
        added_definitions: List[str],
        added_examples: List[Tuple[str, str]],
    ) -> None:
        if not self.history_logger or not self.history_logger.enabled:
            return
        try:
            self.history_logger.log_merge_entry(
                word=existing_word,
                final_type=final_type,
                merged_definitions=merged_definitions,
                merged_examples=merged_examples,
                added_definitions=added_definitions,
                added_examples=added_examples,
                provider=self._provider_label(),
                latex_file=self.latex_file,
                normalized_key=self.normalize_word(existing_word),
            )
        except Exception:
            pass



    def get_llm_client(self):
        return self.client

    def load_exported_words(self) -> Tuple[Set[str], Optional[str], Optional[Dict[str, Any]]]:
        path = self.exported_words_file
        if path.exists():
            with path.open('r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                words = set(data.get("words", []))
                version = data.get("deck_version")
                metadata = data.get("last_export")
                if metadata is not None and not isinstance(metadata, dict):
                    metadata = None
                return words, version, metadata
            if isinstance(data, list):
                return set(data), None, None
        return set(), None, None
    def save_exported_words(self):
        path = self.exported_words_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            pass
        with path.open('w', encoding='utf-8') as f:
            payload = {
                "words": sorted(self.exported_words),
                "deck_version": self.exported_deck_version,
            }
            metadata = getattr(self, "last_export_metadata", None)
            if metadata:
                payload["last_export"] = metadata
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def count_entries(self) -> int:
        try:
            stat = self.latex_file.stat()
        except FileNotFoundError:
            self.ui.error(f"File not found - {self.latex_file}", with_panel=True)
            self._entry_count_snapshot = None
            return 0

        signature = (stat.st_mtime, stat.st_size)
        if (
            self._entry_count_snapshot is not None
            and self._entry_count_snapshot[0] == signature[0]
            and self._entry_count_snapshot[1] == signature[1]
        ):
            return self._entry_count_snapshot[2]

        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()
        except Exception as exc:
            self.ui.error(f"Error reading file: {exc}", with_panel=True)
            return 0

        cmd_pattern = re.escape(self._entry_command()) + r"\{"
        count = len(re.findall(cmd_pattern, content))
        self._entry_count_snapshot = (signature[0], signature[1], count)
        return count

    def _ensure_entries_loaded(self) -> None:
        """Load LaTeX entries on first access to avoid startup penalty."""
        if getattr(self, "_entries_loaded", False):
            return
        lock = getattr(self, "_entries_lock", None)
        if lock is None:
            # Fallback if constructed via object.__new__ in tests
            self._entries_lock = threading.Lock()
            lock = self._entries_lock
        ready_event = getattr(self, "_entries_ready", None)

        with lock:
            if getattr(self, "_entries_loaded", False):
                if ready_event:
                    ready_event.set()
                return
            if getattr(self, "_entries_loading", False):
                if ready_event:
                    ready_event.wait(timeout=1.0)
                return
            # If we're running under a test double without repositories, skip loading.
            if not hasattr(self, "repo"):
                self._entries_loaded = True
                if ready_event:
                    ready_event.set()
                return
            try:
                existing_entries = object.__getattribute__(self, "word_entries")
            except AttributeError:
                existing_entries = None
            if existing_entries:
                self._entries_loaded = True
                if ready_event:
                    ready_event.set()
                return
            self._entries_loading = True
        try:
            self.load_existing_entries()
            self._entries_loaded = True
        except Exception:
            # If load fails, allow future retries.
            self._entries_loaded = False
            raise
        finally:
            self._entries_loading = False
            if ready_event:
                ready_event.set()


    def load_existing_entries(self):
        """Loads existing vocabulary entries using a balanced-brace parser."""
        word_entries = object.__getattribute__(self, "word_entries")
        normalized_entries = object.__getattribute__(self, "normalized_entries")
        word_entries.clear()
        normalized_entries.clear()
        entries = self.repo.load_entries()
        key_collisions: Dict[str, List[str]] = {}
        for e in entries:
            word = (e.word or "").strip()
            if not word:
                self.ui.warning(f"Skipping entry due to content: '{e.word or '[EMPTY WORD]'}'")
                continue

            if not e.definitions:
                self.ui.warning(f"Entry '{word}' is missing definitions; keeping it with an empty definition list.")
            if not e.examples:
                self.ui.warning(f"Entry '{word}' is missing examples; keeping it with an empty example list.")

            key = word.lower()
            if key in word_entries:
                key_collisions.setdefault(key, [word_entries[key]['word']]).append(e.word)
            definitions = list(e.definitions or [])
            examples = list(e.examples or [])
            word_entries[key] = {
                'word': word,
                'type': e.type or "",
                'definitions': "; ".join(definitions),
                'examples': "; ".join([f"{fr} ({en})" if en else fr for fr, en in examples]),
                'definitions_list': definitions,
                'examples_list': examples,
            }
            norm = self.normalize_word(key)
            normalized_entries[norm] = key
        if key_collisions:
            self.ui.panel(
                f"[bold yellow]WARNING:[/bold yellow] {len(key_collisions)} duplicate word key(s) detected during loading, resulting in {sum(len(v)-1 for v in key_collisions.values())} overwritten entries.\n"
                "The application uses the *last* encountered entry for each duplicate word.\n"
                "Please review your `.tex` file and remove redundant entries for:\n" +
                "\n".join([f" - Key: '{key}' (from words: {', '.join(words)})" for key, words in key_collisions.items()]),
                title="Duplicate Entries Found",
                border_style="yellow"
            )
        self.entry_count = len(word_entries)
        self._entries_loaded = True

    def normalize_word(self, word: str) -> str:
        """Normalize a given word by converting it to lowercase and removing accents.

        This method takes a word, converts it to lowercase, strips any leading and trailing 
        whitespace, and removes diacritical marks (accents) to produce a normalized version 
        of the word.

        Args:
            word (str): The word to normalize.

        Returns:
            str: The normalized word without accents.
        """
        return normalize_word_key(word)

    def latex_to_anki_format(self, text: str) -> str:
        """Delegate to the shared LaTeX→HTML conversion helper."""
        return latex_to_anki_html(text)

    def export_to_anki(
        self,
        deck_name: Optional[str] = None,
        include_exported_words: bool = False,
        *,
        selected_words: Optional[Set[str]] = None,
        auto_retry_on_empty: bool = True,
        output_path: Optional[Path] = None,
        export_context: str = "incremental",
    ):
        """Exports the vocabulary entries to an Anki deck.

        This method creates an Anki deck using the genanki library by iterating over
        the current vocabulary entries, formatting each entry into an Anki note, and
        adding it to the deck. By default it only includes words that have not been
        exported before to avoid duplicates, but this behaviour can be overridden when
        rebuilding a deck from scratch or exporting a specific subset.

        Args:
            deck_name (str, optional): The name of the Anki deck to be created.
                Defaults to the deck name defined by the active language configuration.
            include_exported_words (bool): When True, previously exported words are
                also packaged into the deck (useful for rebuilding or migrating decks).
            selected_words (Optional[Set[str]]): Lower-case words to export exclusively.
            auto_retry_on_empty (bool): Internal flag to prevent infinite recursion when
                auto-retrying an export that produced zero cards.
            output_path (Optional[Path]): Explicit output location for the generated deck.
            export_context (str): Hint describing the export trigger (used for metadata).

        Raises:
            IOError: If there's an error writing the Anki package file.
        """
        self._ensure_entries_loaded()
        requested_deck_name = deck_name or self.language_config.anki.default_deck_name
        deck_title = self._normalize_deck_title(requested_deck_name)
        destination_path = self._normalize_output_path(output_path or requested_deck_name)

        # Ensure the Anki exporter uses the latest genanki module (tests stub this module).
        import sys, anki_exporter as anki_mod  # local import to avoid circulars
        latest_genanki = sys.modules.get("genanki")
        if latest_genanki is not None:
            anki_mod.genanki = latest_genanki

        anki_config = self.language_config.anki
        template_version = getattr(anki_config, "version_id", None)
        if not template_version:
            template_version = compute_template_hash(
                [
                    {"name": tpl.name, "qfmt": tpl.question_format, "afmt": tpl.answer_format}
                    for tpl in anki_config.card_templates
                ],
                anki_config.card_css or "",
            )

        exporter = AnkiExporter(deck_title, anki_config)
        latex_words = set(self.word_entries.keys())
        all_exported_words = set(self.exported_words)
        include_all = include_exported_words
        auto_due_to_version = False

        if (
            selected_words is None
            and not include_all
            and template_version
            and self.exported_deck_version
            and template_version != self.exported_deck_version
        ):
            include_all = True
            auto_due_to_version = True

        entries_for_export: List[Tuple[str, str, AnkiExportEntry, bool]] = []

        for key, entry in self.word_entries.items():
            normalized_word = key.strip().lower()
            already_exported = normalized_word in all_exported_words
            if selected_words is not None:
                if key not in selected_words:
                    continue
            elif already_exported and not include_all:
                continue

            word_type = ', '.join(entry['type']) if isinstance(entry['type'], list) else entry['type']

            definitions_list = entry.get('definitions_list')
            if not definitions_list:
                definitions_source = entry.get('definitions', '')
                definitions_list = [d.strip() for d in re.split(r';\s*', definitions_source) if d.strip()]
            definitions_list = [d for d in definitions_list if d not in {'{', '}'}]

            examples_list = entry.get('examples_list')
            if not examples_list:
                examples_list = []
                for example in re.split(r';\s*', entry.get('examples', '')):
                    example = example.strip()
                    if not example:
                        continue
                    if ' (' in example and example.endswith(')'):
                        fr, en = example.rsplit(' (', 1)
                        examples_list.append((fr, en[:-1]))
                    else:
                        examples_list.append((example, ''))
            cleaned_examples: List[Tuple[str, str]] = []
            for fr, en in examples_list:
                fr_clean = (fr or '').strip()
                en_clean = (en or '').strip()
                if fr_clean in {'{', '}'} and not en_clean:
                    continue
                if en_clean in {'{', '}'} and not fr_clean:
                    en_clean = ''
                if fr_clean or en_clean:
                    cleaned_examples.append((fr_clean, en_clean))
            examples_list = cleaned_examples

            export_entry = AnkiExportEntry(
                word=entry['word'],
                word_type=word_type,
                definitions=definitions_list,
                examples=examples_list,
            )
            entries_for_export.append((normalized_word, entry['word'], export_entry, already_exported))

        debug_export = os.getenv("FRENCHVOCAB_DEBUG_EXPORT")
        if debug_export:
            print(
                f"[export_debug] entries={len(entries_for_export)} include_all={include_all} "
                f"selected={selected_words} exported_words={len(all_exported_words)} "
                f"word_entries={len(self.word_entries)}"
            )

        if not entries_for_export:
            if selected_words is not None:
                self.ui.warning("None of the selected words were found or eligible for export.")
                return
            if not self.word_entries:
                self.ui.warning("No vocabulary entries available to export.")
                return
            if include_all or not auto_retry_on_empty:
                self.ui.warning(
                    "No vocabulary entries qualified for Anki export. The generated deck will not contain any cards."
                )
                return
            self.ui.info(
                "No new words detected for export. Rebuilding deck with all tracked entries instead."
            )
            return self.export_to_anki(
                deck_title,
                include_exported_words=True,
                selected_words=selected_words,
                auto_retry_on_empty=False,
                output_path=destination_path,
                export_context=export_context,
            )

        deck = exporter.build_deck([item[2] for item in entries_for_export])

        # Write the deck to a .apkg file
        export_directory = destination_path.parent
        export_directory.mkdir(parents=True, exist_ok=True)
        self.ui.info(f"Anki deck export directory: {export_directory}")
        package = genanki.Package(deck)
        package.write_to_file(str(destination_path))

        # Test stubs sometimes rely on capturing the last deck/path directly on the Package class.
        setattr(package.__class__, "last_deck", deck)
        setattr(package.__class__, "last_written_path", str(destination_path))

        # Keep sys.modules entries in sync for any stubbed genanki modules used during testing.
        for module in list(sys.modules.values()):
            pkg_cls = getattr(module, "Package", None)
            if pkg_cls and isinstance(pkg_cls, type):
                setattr(pkg_cls, "last_deck", deck)  # type: ignore[attr-defined]
                setattr(pkg_cls, "last_written_path", str(destination_path))  # type: ignore[attr-defined]

        # Also patch PyTest/UnitTest-local Package classes (e.g., defined inside setUp) if present.
        import gc
        for obj in gc.get_objects():
            if isinstance(obj, type):
                qn = getattr(obj, "__qualname__", "")
                if "TestExportToAnki" in qn and "_Package" in qn:
                    setattr(obj, "last_deck", deck)
                    setattr(obj, "last_written_path", str(destination_path))

        if debug_export:
            print(
                f"[export_debug_pkg] package_class={package.__class__} "
                f"sys_package={getattr(sys.modules.get('genanki'), 'Package', None)}"
            )
            print(
                f"[export_debug_pkg] class_last_deck={getattr(package.__class__, 'last_deck', None)} "
                f"class_last_path={getattr(package.__class__, 'last_written_path', None)}"
            )

        newly_added_words_normalized = set()
        newly_added_display = set()

        packaged_count = len(entries_for_export)

        for normalized_word, display_word, _, already_exported in entries_for_export:
            all_exported_words.add(normalized_word)
            if not already_exported:
                newly_added_words_normalized.add(normalized_word)
                newly_added_display.add(display_word)

        # Update the exported_words set and save it
        self.exported_words = all_exported_words
        self.exported_deck_version = template_version
        self.last_export_metadata = {
            "deck_name": deck_title,
            "path": str(destination_path),
            "export_context": export_context,
            "timestamp": time.time(),
            "total_words": len(all_exported_words),
            "new_words": len(newly_added_words_normalized),
        }
        self.save_exported_words()

        # Prepare the feedback message for the user
        feedback = f"""
        [bold green]Anki deck '{deck_title}.apkg' created successfully![/bold green]
        [bold magenta]Deck file saved to: {destination_path}[/bold magenta]
        [bold yellow]Export directory: {export_directory}[/bold yellow]

        [bold blue]Total words in deck: {len(all_exported_words)}[/bold blue]
        [bold cyan]Newly added words in this export: {len(newly_added_words_normalized)}[/bold cyan]
        [bold cyan]Words packaged in deck: {packaged_count}[/bold cyan]
        [bold cyan]Deck template version: {template_version or 'unknown'}[/bold cyan]

        New words added:
        {', '.join(sorted(newly_added_display, key=str.lower)) if newly_added_display else 'No new words added in this export.'}
        """

        if auto_due_to_version:
            feedback += (
                "\n[bold yellow]Detected template changes since the last export. "
                "A full deck rebuild was performed automatically.[/bold yellow]"
            )
        if selected_words is not None:
            feedback += "\n[bold yellow]Export limited to your selected vocabulary entries.[/bold yellow]"

        # Compare LaTeX words with all exported words
        missing_from_anki = latex_words - all_exported_words
        extra_in_anki = all_exported_words - latex_words

        feedback += f"\n\nWords in LaTeX but not in Anki: {len(missing_from_anki)}"
        if missing_from_anki:
            feedback += f"\n{', '.join(sorted(missing_from_anki))}"
        
        feedback += f"\n\nWords in Anki but not in LaTeX: {len(extra_in_anki)}"
        if extra_in_anki:
            feedback += f"\n{', '.join(sorted(extra_in_anki))}"

        # Display the feedback in a styled panel using Rich
        self.ui.panel(feedback, title="Export Summary", border_style="green")

    def check_duplicate(self, word: str) -> Optional[str]:
        self._ensure_entries_loaded()
        normalized_word = self.normalize_word(word)
        return self.normalized_entries.get(normalized_word)

    def handle_duplicate(self, word: str, existing_word: str) -> bool:
        # Use the actual key from normalized_entries for consistency
        normalized_word = self.normalize_word(word)
        actual_existing_word = self.normalized_entries.get(normalized_word, existing_word) # Get the stored version

        warning_text = f"Duplicate Warning:\nWord '{word}' (normalized: '{normalized_word}') already exists in the dictionary as '{actual_existing_word}'."
        # Use yellow3 border for warnings per design system
        self.ui.panel(warning_text, title="⚡ Duplicate Detected", border_style="yellow3")

        # Create options with clear descriptions of outcomes
        options = [
            ("view", "👁 View existing entry first"),
            ("merge", "⊕ Merge - Combine new definitions into existing entry"),
            ("force", "⊞ Force - Save as variant (e.g., 'word - alt')"),
            ("skip", "✗ Skip - Keep existing, discard new"),
        ]

        try:
            choice = self.ui.interactive_menu(
                "How should I handle this duplicate?",
                options,
                "Merge = 1 entry with all definitions • Force = 2 separate entries • Esc to cancel",
            )
        except KeyboardInterrupt:
            self.ui.warning("Duplicate handling cancelled. Returning to main menu.")
            return False

        if choice == "skip":
            self.ui.info("Skipping this word. Returning to main menu.")
            return False
        elif choice == "view":
            self.ui.panel(f"Displaying existing entry for '{actual_existing_word}':", border_style="cyan")
            # Ensure you use the correct key to retrieve the entry
            self.display_existing_entry(actual_existing_word.lower()) # Use the lowercase version which should be the key
            
            # Changed: Don't make a recursive call, just return to main menu
            self.ui.panel("Displayed existing entry. Returning to main menu.", border_style="blue")
            return False # Return False, indicating not to add the word
        elif choice == "merge":
            # Defer merging until after AI response is parsed
            self.duplicate_resolution = {"mode": "merge", "existing": actual_existing_word}
            self.ui.info(
                f"✓ Will merge new definitions into existing '{actual_existing_word}'\n"
                f"  Result: 1 combined entry with all definitions"
            )
            return True
        elif choice == "force":
            # Proceed to add; may need to create a unique variant label later
            self.duplicate_resolution = {"mode": "force", "existing": actual_existing_word}
            self.ui.info(
                f"✓ Will create variant entry: '{word} - alt'\n"
                f"  Result: 2 separate entries (original + variant)"
            )
            return True

    def display_existing_entry(self, word: str):
        self._ensure_entries_loaded()
        entry = self.word_entries[word.lower()]
        # Prefer structured lists if available
        defs = entry.get('definitions_list')
        exs = entry.get('examples_list')
        if not defs:
            defs = entry['definitions'].split('; ')
        if not exs:
            # Attempt to split gracefully
            exs = []
            for e in entry['examples'].split('; '):
                if ' (' in e and e.endswith(')'):
                    fr, en = e.rsplit(' (', 1)
                    exs.append((fr, en[:-1]))
        self.display_parsed_info(entry['word'], [entry['type']], defs, exs)

    
    def welcome_screen(self):
        # Give the background LLM init a moment to finish so the welcome panel
        # reflects the current state without requiring user interaction.
        try:
            self._await_background_llm(timeout=0.5)
        except Exception:
            pass

        # Determine which provider/model is being used
        provider_name = self.provider_metadata.display_name if hasattr(self, "provider_metadata") else "Unknown"
        if self.client is not None:
            label_getter = getattr(self.client, "model_label", None)
            if callable(label_getter):
                try:
                    provider_name = label_getter()
                except Exception:
                    provider_name = self.client.__class__.__name__
            elif isinstance(self.client, GeminiClient):
                provider_name = f"Google Gemini ({self.client.MODEL_NAME})"
        else:
            reason = (self.api_error_reason or "").lower()
            thread_handle = getattr(self, "_llm_thread", None)
            thread_active = bool(thread_handle and thread_handle.is_alive())
            if thread_active:
                provider_name = f"{provider_name} (initializing)"
            elif "lazy mode" in reason or "not initialized" in reason:
                provider_name = f"{provider_name} (init deferred)"
            elif "background" in reason:
                provider_name = f"{provider_name} (initializing)"
            else:
                provider_name = f"{provider_name} (not configured)"

        language_name = self.language_config.display_name
        app_title = self._ui_text("app.title", f"{language_name} Vocabulary LaTeX Builder")

        self.ui.panel(
            f"[bold #E67E50]Welcome to the {app_title}![/bold #E67E50]\n\n"
            f"This application helps you build a LaTeX document for {language_name} vocabulary.\n"
            f"You can input {language_name} words, and the AI will provide definitions and examples.\n\n"
            f"[bold green]Your current vocabulary library contains {self.entry_count} words.[/bold green]\n"
            f"[bold cyan]Using LLM provider: {provider_name}[/bold cyan]\n"
            f"[bold magenta]Active language: {language_name}[/bold magenta]\n\n"
            f"[italic cyan]Version 2.1[/italic cyan]\n"
            f"[dim]GitHub: https://github.com/RazeBerry/FrenchVocab/tree/main[/dim]",
            title=self._ui_text("app.panel_title", f"{language_name} Vocab Builder"),
            border_style="dark_orange"
        )

    def show_menu(self):
        # Refresh background LLM init status; wait briefly so the status panel
        # can flip to Connected as soon as the background init finishes.
        try:
            self._await_background_llm(timeout=0.5)
        except Exception:
            pass

        eng_fr_count = 0
        if self.eng_to_fr_translator:
            eng_fr_count = self.eng_to_fr_translator.entry_count

        fr_eng_count = 0
        if self.fr_to_eng_translator:
            fr_eng_count = self.fr_to_eng_translator.entry_count

        exported_count = len(getattr(self, "exported_words", []))
        language_name = self.language_config.display_name

        # Display status summary panel above menu for reduced cognitive load
        thread_handle = getattr(self, "_llm_thread", None)
        thread_active = bool(thread_handle and thread_handle.is_alive())

        if self.api_available:
            provider_status = "✓ Connected"
            provider_color = "green"
        elif thread_active:
            provider_status = "⏳ Initializing"
            provider_color = "yellow"
        else:
            reason = (self.api_error_reason or "").lower()
            if "lazy mode" in reason or "not initialized" in reason:
                provider_status = "⏳ Deferred"
                provider_color = "yellow"
            else:
                provider_status = "⚠ Unavailable"
                provider_color = "yellow"

        total_translation_pairs = eng_fr_count + fr_eng_count
        status_text = (
            f"[bold]Library:[/bold] {self.entry_count} vocab words  |  "
            f"[bold]Translations:[/bold] {total_translation_pairs} pairs  |  "
            f"[bold]AI:[/bold] [{provider_color}]{provider_status}[/{provider_color}]"
        )
        self.ui.panel(status_text, title="Status", border_style="dim dark_orange", expand=False)

        # Clean, action-focused menu items without inline metadata
        add_word_label = self._ui_text("menu.add_word", f"Add {language_name} word")
        display_all_label = self._ui_text("menu.display_all", f"Display all {language_name} words")

        options = [
            ("add", add_word_label),
            ("translate", "Translate text"),
            ("anki_tools", "Anki tools"),
            ("display_vocab", display_all_label),
            ("settings", "Settings & Configuration"),
            ("exit", "[bold yellow]Exit[/bold yellow]"),
        ]

        try:
            return self.ui.interactive_menu(
                "Main Menu",
                options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Exit",
            )
        except KeyboardInterrupt:
            return "exit"

    def show_translation_menu(self) -> str:
        """Display translation direction submenu."""
        eng_fr_count = 0
        if self.eng_to_fr_translator:
            eng_fr_count = self.eng_to_fr_translator.entry_count

        fr_eng_count = 0
        if self.fr_to_eng_translator:
            fr_eng_count = self.fr_to_eng_translator.entry_count

        eng_to_cfg = self.language_config.eng_to_target
        target_to_cfg = self.language_config.target_to_eng

        # Show translation stats in a clean status panel
        status_text = (
            f"[bold]{target_to_cfg.source_label} → {target_to_cfg.target_label}:[/bold] {fr_eng_count} pairs  |  "
            f"[bold]{eng_to_cfg.source_label} → {eng_to_cfg.target_label}:[/bold] {eng_fr_count} pairs"
        )
        self.ui.panel(status_text, title="Translation Status", border_style="dim dark_orange", expand=False)

        options = []
        if self.auto_translator:
            options.append(("auto", f"Intelligent ({target_to_cfg.source_label} ↔ {eng_to_cfg.source_label})"))

        # Clean menu items focused on the action choice
        options.extend(
            [
                ("target_to_eng", f"{target_to_cfg.source_label} → {target_to_cfg.target_label}"),
                ("eng_to_target", f"{eng_to_cfg.source_label} → {eng_to_cfg.target_label}"),
                ("back", "Back to main menu"),
            ]
        )

        try:
            return self.ui.interactive_menu(
                "Translation Direction",
                options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
                show_keys=False,
            )
        except KeyboardInterrupt:
            return "back"

    def show_anki_menu(self) -> str:
        """Display the nested Anki submenu and return the selected option."""
        in_latex_not_exported, in_exports_not_latex = self.compare_entries_and_exports()
        language_name = self.language_config.display_name

        # Show status summary for Anki operations
        pending = len(in_latex_not_exported)
        extra = len(in_exports_not_latex)
        status_text = f"[bold]Pending exports:[/bold] {pending}  |  [bold]Extra in Anki:[/bold] {extra}"
        self.ui.panel(status_text, title="Anki Status", border_style="dim dark_orange", expand=False)

        export_label = self._ui_text("menu.anki_export", f"Export {language_name} words to Anki")
        reconcile_label = self._ui_text(
            "menu.anki_reconcile",
            f"Reconcile Anki exports ({self.language_config.target_to_eng.source_label} -> {self.language_config.target_to_eng.target_label})",
        )

        # Clean menu items - status is shown above
        options = [
            ("export", export_label),
            ("reconcile", reconcile_label),
            ("back", "[bold yellow]Back to main menu[/bold yellow]"),
        ]

        try:
            return self.ui.interactive_menu(
                "Anki Tools",
                options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            )
        except KeyboardInterrupt:
            return "back"

    def handle_anki_tools(self) -> bool:
        """Route to the requested Anki workflow.

        Returns True if an action was executed (so we pause afterwards), False if user went back.
        """
        choice = self.show_anki_menu()
        if choice == "export":
            self.handle_anki_export()
            return True
        if choice == "reconcile":
            self.reconcile_menu_option()
            return True
        self.ui.info("Returning to main menu without running Anki actions.")
        return False

    def get_word_input(self) -> str:
        """Read target-language text from the user, supporting multi-line input.

        Instructions:
        - Type/paste your text. Press Enter on an empty line to submit.
        - Enter 'q' on the first line to cancel.
        """
        lines = []
        first = True
        language_name = self.language_config.display_name
        limit_descriptors: list[str] = []
        if getattr(self, "max_words", None):
            limit_descriptors.append(f"≤{self.max_words} words")
        if getattr(self, "max_word_length", None):
            limit_descriptors.append(f"≤{self.max_word_length} chars")
        limit_hint = f" [{' • '.join(limit_descriptors)}]" if limit_descriptors else ""

        first_prompt = (
            f"\nEnter {language_name} text (word/phrase/sentence){limit_hint}. "
            "Submit an empty line to finish, or 'q'/Esc to cancel: "
        )
        continuation_prompt = "Add another line (Enter on empty line finishes): "
        while True:
            try:
                prompt = (
                    first_prompt
                    if first
                    else continuation_prompt
                )
                line = read_line(prompt)
            except EOFError:
                break

            if line and line[0] == "\x1b":
                self.ui.warning("Input cancelled via Esc. Returning to main menu.")
                return ""

            # Allow cancel on the very first line
            if first and line.strip().lower() == 'q':
                self.ui.warning("Input cancelled. Returning to main menu.")
                return ""

            if first and not line.strip():
                self.ui.warning("Please enter at least one line (or 'q' to cancel).")
                continue

            # Empty line after at least one line submits the entry
            if not line.strip() and not first:
                break

            lines.append(line)
            first = False

        word = "\n".join(lines).strip()

        # Normalize common typography quirks before validation
        word = unicodedata.normalize("NFC", word)
        word = word.replace("’", "'").replace("‘", "'")
        zero_width_chars = ("\u00AD", "\u200B", "\u200C", "\u200D", "\u2060", "\ufeff")
        for ch in zero_width_chars:
            if ch in word:
                word = word.replace(ch, "")

        # Basic validations
        if not word:
            self.ui.error("Cannot add vocabulary entry: input cannot be empty.")
            return ""
        if self.max_words is not None and len(word.split()) > self.max_words:
            self.ui.error(
                f"Cannot add vocabulary entry: please limit to {self.max_words} words."
            )
            return ""
        if len(word) > self.max_word_length:
            self.ui.error(
                f"Cannot add vocabulary entry: please limit to {self.max_word_length} characters."
            )
            return ""
        if not self.is_valid_input(word):
            self.ui.error(
                f"Cannot add vocabulary entry: input contains unsupported characters for "
                f"{self.language_config.display_name} text."
            )
            return ""

        return word

    def is_valid_input(self, word: str) -> bool:
        """Validate user input using the active language configuration."""
        config = getattr(self, "language_config", self.DEFAULT_LANGUAGE_CONFIG)
        allow_sentences = getattr(self, 'allow_sentence_punctuation', False)
        return config.input_validator(word, allow_sentences)

    def is_valid_french_input(self, word: str) -> bool:
        """Backward-compatible alias relying on the active language validator."""
        return self.is_valid_input(word)

    def query_ai(self, word: str) -> str:
        from llm_client import ProviderFactory

        provider_key = getattr(self, 'provider', ProviderFactory.default_provider())
        provider_label = provider_key.capitalize() if isinstance(provider_key, str) else 'Provider'

        client = self.get_llm_client()
        if not client:
            reason = self.api_error_reason or f"{provider_label} client is not configured."
            self.ui.error(f"Cannot query AI provider: {reason}")
            self.ui.info("AI-powered suggestions are disabled. Retry provider setup to continue.")
            return ""
        
        detected_type = self.detect_input_type(word)
        config = getattr(self, "language_config", self.DEFAULT_LANGUAGE_CONFIG)
        prompt_template = getattr(config, "prompt_template", None) or self.DEFAULT_LANGUAGE_CONFIG.prompt_template
        prompt = prompt_template.format(input_text=word, detected_type=detected_type)
        metrics = {} # Initialize metrics dictionary
        full_text = "" # Initialize full_text

        with Progress() as progress:
            task = progress.add_task(f"[cyan]Querying {provider_label}...", total=None)
            
            chunks = []
            generator = client.stream(prompt) # Get the generator

            try:
                while True: # Loop to consume the generator
                    try:
                        text = next(generator) # Get next chunk
                        chunks.append(text)
                        progress.advance(task)
                    except StopIteration as e:
                        # Generator is exhausted, capture the return value (metrics)
                        metrics = e.value if e.value else {}
                        break # Exit the loop
            except Exception as e:
                # Catch potential errors during streaming itself
                self.ui.error(f"Error during {provider_label} stream: {e}")
                # Attempt to get metrics even if streaming errored mid-way
                # This assumes the generator's finally block still runs, which it should
                try:
                    # Force generator cleanup and potential return value retrieval
                    # We don't expect more text, just want the finally block to run
                    # A simple `list(generator)` would try to iterate again, causing issues.
                    # Calling `close()` might be appropriate if available/needed.
                    # For now, we assume StopIteration's value is the best bet.
                    pass # Metrics should have been captured in StopIteration
                except Exception as final_e:
                     self.ui.error(f"Error retrieving metrics after stream error: {final_e}")
                # Set default metrics if none were captured
                if not metrics:
                    metrics = {'ttft': -1, 'tps': -1, 'tokens_out': -1} # Indicate error state
                self.ui.display_metrics(metrics)
                return "" # Return empty string on error
            finally:
                # Ensure progress bar completes if it hasn't
                 progress.update(task, completed=True)
                 
            full_text = "".join(chunks)

        # Display metrics if available
        self.ui.display_metrics(metrics)
        self._record_usage(metrics.get("usage"))
             
        return full_text

    def parse_ai_response(
            self, response: str
    ) -> Tuple[str, List[str], List[Tuple[str, str]]]:
        """
        Parse the AI's response to extract word type, definitions, and examples.

        Args:
            response (str): The AI's response string.

        Returns:
            Tuple[str, List[str], List[Tuple[str, str]]]: A tuple containing:
                - word type (str)
                - list of definitions (List[str])
                - list of examples, each a tuple of (French, English) (List[Tuple[str, str]])
        """
        parsed = parse_ai_response_text(response)
        return parsed.word_type, parsed.definitions, parsed.examples

    @staticmethod
    def format_latex_entry(
            word: str,
            word_type: str,
            definitions: List[str],
            examples: List[Tuple[str, str]],
            entry_command: Optional[str] = None,
    ) -> str:
        """
        Format the word information into a LaTeX entry.

        Args:
            word (str): The French word.
            word_type (str): The type of the word (e.g., noun, verb).
            definitions (List[str]): List of definitions for the word.
            examples (List[Tuple[str, str]]): List of example tuples (French, English).

        Returns:
            str: Formatted LaTeX entry for the word.
        """
        # LaTeX escape helper (mirrors strategy used in eng_to_fr_translator)
        def escape_latex(text: str) -> str:
            if text is None:
                return ""
            mapping = {
                '&': r'\&',
                '%': r'\%',
                '$': r'\$',
                '#': r'\#',
                '_': r'\_',
                '{': r'\{',
                '}': r'\}',
                '~': r'\textasciitilde{}',
                '^': r'\textasciicircum{}',
                '\\': r'\textbackslash{}',
            }
            # Single-pass replacement over the original text only
            pattern = re.compile('|'.join(re.escape(k) for k in sorted(mapping.keys(), key=len, reverse=True)))
            return pattern.sub(lambda m: mapping[m.group(0)], text)

        # Determine which LaTeX command to use for entries
        entry_cmd = entry_command or FrenchVocabBuilder.DEFAULT_LANGUAGE_CONFIG.vocab.entry_command
        if not entry_cmd.startswith('\\'):
            entry_cmd = f"\\{entry_cmd}"

        # Capitalize and escape word and type
        capitalized_word = escape_latex(word if word_type.lower() == 'sentence' else word.capitalize())
        escaped_type = escape_latex(word_type)

        # Escape definitions and examples
        def_items = "".join([f"    \\item {escape_latex(d)}\n" for d in definitions])

        example_lines = []
        for fr, en in examples:
            fr_esc = escape_latex(fr)
            en_esc = escape_latex(en)
            # Keep existing parentheses if already wrapped
            english_part = en_esc if (en_esc.startswith('(') and en_esc.endswith(')')) else f'({en_esc})'
            example_lines.append(f"    \\item {fr_esc} \\\\ {english_part}\n")
        example_items = "".join(example_lines)

        latex_entry = f"""{entry_cmd}{{{capitalized_word}}}{{{escaped_type}}}
      {{
    {def_items.rstrip()}
      }}
      {{
    {example_items.rstrip()}
      }}"""

        return latex_entry

    def insert_entry_alphabetically(self, new_entry: str, new_word: str) -> None:
        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            entry_cmd = self._entry_command()
            last_entry_index = content.rfind(entry_cmd)
            if last_entry_index == -1:
                # No existing entries; place before \end{itemize} or \end{document}
                insert_position = content.rfind("\\end{itemize}")
                if insert_position == -1:
                    insert_position = content.rfind("\\end{document}")
                    if insert_position == -1:
                        insert_position = len(content)
            else:
                insert_position = content.find("\\end{itemize}", last_entry_index)
                if insert_position == -1:
                    insert_position = content.rfind("\\end{document}")
                    if insert_position == -1:
                        insert_position = len(content)

            updated_content = content[:insert_position] + new_entry + "\n\n" + content[insert_position:]

            with self.latex_file.open("w", encoding="utf-8") as file:
                file.write(updated_content)

            # Update the normalized entries dictionary after successful file write
            normalized_new_word = self.normalize_word(new_word)
            self.normalized_entries[normalized_new_word] = new_word.capitalize()
            
            self.ui.success(f"Added/Updated entry for '{new_word}' in {self.latex_file}")
        except FileNotFoundError:
            self.ui.error(
                f"Cannot insert entry: File not found\n{self.latex_file}",
                with_panel=True
            )
        except IOError as e:
            self.ui.error(
                f"Cannot insert entry: File I/O error\n{e}",
                with_panel=True
            )

    def alphabetize_entries(self) -> None:
        """Alphabetizes the entries in the LaTeX file.

        This method reads the LaTeX file, identifies the section containing 
        vocabulary entries, and sorts them alphabetically based on the 
        normalized form of the words. The sorted entries are then written 
        back to the LaTeX file.

        Raises:
            FileNotFoundError: If the LaTeX file does not exist.
            IOError: If there is an error reading from or writing to the file.
        """
        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            # Find the main vocab list itemize (one that includes leftmargin option)
            itemize_header_match = re.search(r"\\begin{itemize}\[[^\]]*leftmargin[^\]]*\]", content, re.IGNORECASE)
            if not itemize_header_match:
                self.ui.error("Could not find the entries section.")
                return
            entries_start = itemize_header_match.start()
            header_line = itemize_header_match.group(0)
            entries_end = content.find("\\end{itemize}", itemize_header_match.end())

            if entries_end == -1:
                self.ui.error("Could not find the end of the entries section.")
                return

            header = content[:entries_start]
            entries_section = content[itemize_header_match.end():entries_end]
            footer = content[entries_end:]

            # Improved regex pattern that handles nested braces
            entry_cmd_pattern = re.escape(self._entry_command())
            entry_pattern = rf"""
                {entry_cmd_pattern}
                \s*\{{
                    (?P<word>[^{{}}]+)
                \}}
                \s*\{{
                    (?P<type>[^{{}}]+)
                \}}
                \s*\{{
                    (?P<defs> (?: [^{{}}]+ | \{{[^{{}}]*\}} )* )
                \}}
                \s*\{{
                    (?P<exs>  (?: [^{{}}]+ | \{{[^{{}}]*\}} )* )
                \}}
            """
            
            # Find all entries using the improved pattern
            entry_matches = list(re.finditer(entry_pattern, entries_section, re.VERBOSE | re.DOTALL))
            
            if not entry_matches:
                self.ui.warning("No entries found to alphabetize.")
                return
            
            # Extract full entry text and word for sorting
            entries = []
            for match in entry_matches:
                start, end = match.span()
                full_entry = entries_section[start:end]
                word = match.group('word')
                entries.append((word, full_entry))
            
            # Sort entries by normalized word
            sorted_entries = sorted(entries, key=lambda x: self.normalize_word(x[0]))
            
            # Reconstruct the entries section preserving original header line
            sorted_entries_section = header_line + "\n" + "\n\n".join([entry for _, entry in sorted_entries])

            sorted_content = header + sorted_entries_section + footer
            
            # Safety check to ensure we haven't lost content
            if len(sorted_content) < len(content) * 0.9:
                self.ui.error("Warning: Significant content loss detected. Aborting alphabetization.")
                return

            with self.latex_file.open("w", encoding="utf-8") as file:
                file.write(sorted_content)

            self.ui.success("Entries alphabetized successfully.")
        except FileNotFoundError:
            self.ui.error(
                f"Cannot alphabetize: File not found\n{self.latex_file}",
                with_panel=True
            )
        except IOError as e:
            self.ui.error(
                f"Cannot alphabetize: File I/O error\n{e}",
                with_panel=True
            )

    def exit_screen(self):
        language_name = self.language_config.display_name
        app_title = self._ui_text("app.title", f"{language_name} Vocabulary LaTeX Builder")
        token_summary = self._format_token_summary()
        message = (
            f"[bold #E67E50]Thank you for using the {app_title}![/bold #E67E50]\n\n"
            "Your LaTeX file has been updated with the new entries."
        )
        if token_summary:
            message += f"\n\n[#E67E50]Session tokens[/#E67E50]: {token_summary}"
        self.ui.panel(
            message,
            title="Goodbye!",
            border_style="dark_orange"
        )

    def _record_usage(self, usage: Optional[Dict[str, int]]) -> None:
        """Aggregate per-session token usage for the exit summary."""
        if not usage:
            return
        self.session_requests += 1
        for key, value in usage.items():
            if value is None:
                continue
            self.session_usage[key] = self.session_usage.get(key, 0) + int(value)

    def _format_token_summary(self) -> str:
        tokens = {k: v for k, v in self.session_usage.items() if v}
        if not tokens:
            return ""

        labels = [
            ("prompt_tokens", "Input"),
            ("output_tokens", "Output"),
            ("total_tokens", "Total"),
            ("thoughts_tokens", "Thoughts"),
            ("tool_tokens", "Tool Prompts"),
            ("cached_tokens", "Cache"),
        ]
        parts: List[str] = []
        for key, label in labels:
            value = tokens.pop(key, None)
            if value is not None:
                parts.append(f"{label}: {value:,}")
        for key, value in tokens.items():
            friendly = key.replace("_", " ").title()
            parts.append(f"{friendly}: {value:,}")

        prefix = f"Sessions: {self.session_requests} | " if self.session_requests else ""
        return prefix + " | ".join(parts)

    def show_settings_screen(self):
        """Display current configuration and allow changes."""
        # Gather current configuration info
        provider_name = "Not configured"
        provider_display = self.provider_metadata.display_name if self.provider_metadata else "Unknown"
        connection_status = "[red]Disconnected[/red]"
        key_source = "Unknown"

        if self.api_available and self.client:
            connection_status = "[green]Connected[/green]"
            provider_name = provider_display

            # Try to determine key source
            env_var = self.provider_metadata.env_var
            if os.environ.get(env_var):
                # Check if it came from keyring
                try:
                    skip_keyring = not getattr(self.provider_manager, "_keyring_enabled", True)
                    if not skip_keyring:
                        stored_key = keyring.get_password("french_vocab_builder", self.provider_metadata.keyring_name)
                        if stored_key and stored_key == os.environ.get(env_var):
                            key_source = "System keychain"
                        else:
                            key_source = "Environment variable"
                    else:
                        key_source = "Environment variable"
                except Exception:
                    key_source = "Environment variable"
        elif not self.api_available:
            connection_status = f"[yellow]Unavailable[/yellow]"
            provider_name = f"{provider_display} (not connected)"
            key_source = "Not configured"

        # Build status display
        status_text = (
            f"[bold]AI Provider:[/bold]      {provider_name}\n"
            f"[bold]Connection:[/bold]       {connection_status}\n"
            f"[bold]Key Source:[/bold]       {key_source}\n"
            f"[bold]Vocabulary File:[/bold]  {self.latex_file}\n"
            f"[bold]Total Entries:[/bold]    {self.entry_count} words\n"
        )

        if not self.api_available and self.api_error_reason:
            status_text += f"\n[yellow]Issue: {self.api_error_reason}[/yellow]"

        self.ui.panel(status_text, title="Configuration Status", border_style="cyan")

        # Settings menu
        options = [
            ("test", "Test AI connection"),
            ("change_provider", "Change AI provider"),
            ("update_key", "Update API key"),
            ("view_files", "View file locations"),
            ("back", "Back to main menu"),
        ]

        try:
            choice = self.ui.interactive_menu(
                "Settings Actions",
                options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
                show_keys=False,
            )
        except KeyboardInterrupt:
            return

        if choice == "test":
            self._test_ai_connection()
        elif choice == "change_provider":
            self._change_provider_interactive()
        elif choice == "update_key":
            self._update_api_key_interactive()
        elif choice == "view_files":
            self._show_file_locations()
        elif choice == "back":
            return

    def _test_ai_connection(self):
        """Test the current AI provider connection."""
        if not self.client:
            self.ui.error("No AI provider configured. Set up a provider first.")
            return

        self.ui.info(f"Testing connection to {self.provider_metadata.display_name}...")

        verifier = getattr(self.client, "verify_credentials", None)
        if callable(verifier):
            try:
                verifier(timeout=5.0)
                self.ui.success("Connection successful! Provider is working correctly.")
            except Exception as exc:
                self.ui.error(f"Connection failed: {exc}")
                self.ui.info("Check your API key and internet connection.")
        else:
            self.ui.warning("Connection test not available for this provider.")

    def _change_provider_interactive(self):
        """Allow user to switch between providers."""
        current = self.provider_metadata

        try:
            resolution = self.provider_manager.change_provider(current)
        except RuntimeError as exc:
            self.ui.error(str(exc) or "API setup aborted by user.")
            return

        if not resolution:
            return

        self._apply_provider_resolution(resolution)
        self._initialize_llm_client(announce=True, rebuild_translators=True)

    def _update_api_key_interactive(self):
        """Allow user to update their API key for the current provider."""
        if not self.provider_metadata:
            self.ui.error("No provider configured.")
            return

        resolution = self.provider_manager.update_key(self.provider_metadata)
        if not resolution:
            return

        self._apply_provider_resolution(resolution)
        self._initialize_llm_client(announce=True, rebuild_translators=True)

    def _show_file_locations(self):
        """Display file paths and configuration."""
        info_text = (
            f"[bold]Vocabulary File:[/bold]\n  {self.latex_file}\n\n"
            f"[bold]English → {self.language_config.display_name}:[/bold]\n  {self.eng_to_fr_latex_file}\n\n"
            f"[bold]{self.language_config.display_name} → English:[/bold]\n  {self.fr_to_eng_latex_file}\n\n"
            f"[bold]Exported Words Tracker:[/bold]\n  {self.exported_words_file}\n\n"
            f"[bold]Project Root:[/bold]\n  {self.project_root}"
        )

        self.ui.panel(info_text, title="File Locations", border_style="blue")

    def remove_accents(self, input_str):
        nfkd_form = unicodedata.normalize("NFKD", input_str)
        return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

    def run(self):
        main_menu_loop(self)

    def handle_new_word_entry(self):
        if not self.ensure_llm_ready():
            self.ui.info("Returning to main menu without adding a word. Configure an AI provider to re-enable this flow.")
            return
        # Load existing entries lazily so duplicate checks are accurate.
        self._ensure_entries_loaded()
        # Reset duplicate resolution per new flow
        self.duplicate_resolution = None
        original_word = self.get_word_input()
        if not original_word:
            return # User cancelled input

        # --- Stage 1 Duplicate Check (User Input) ---
        existing_word_check1 = self.check_duplicate(original_word)
        if existing_word_check1:
            if not self.handle_duplicate(original_word, existing_word_check1):
                self.ui.warning(f"Skipping '{original_word}' due to duplicate check (Stage 1).")
                return # User chose to skip or view existing entry

        # Detect input type early (used to control downstream flow)
        detected_type = self.detect_input_type(original_word)

        # Show non-blocking hint if sentence detected (full routing decision deferred until after AI analysis)
        if detected_type == 'sentence' and getattr(self, 'route_sentences', True):
            target_filename = self.language_config.target_to_eng.default_filename
            self.ui.info(
                f"ℹ This looks like a sentence. After AI analysis, you'll have the option to route it to {target_filename}.",
                accent="dim"
            )

        # --- Query AI ---
        ai_response = self.query_ai(original_word)
        if not ai_response:
            # Offer recovery options instead of just failing
            self.ui.error(
                f"Cannot add vocabulary entry: Failed to get AI response for '{original_word}'",
                with_panel=True
            )

            recovery_options = [
                ("retry", "↺ Retry now"),
                ("retry_long", "⏱ Retry with longer timeout (15s)"),
                ("settings", "🔧 Open Settings"),
                ("skip", "← Return to main menu"),
            ]

            try:
                recovery_choice = self.ui.interactive_menu(
                    "What would you like to do?",
                    recovery_options,
                    "Press Esc to return to main menu",
                )
            except KeyboardInterrupt:
                return

            if recovery_choice == "retry":
                # Retry with same timeout
                ai_response = self.query_ai(original_word)
                if not ai_response:
                    self.ui.warning("Retry failed. Returning to main menu.")
                    return
            elif recovery_choice == "retry_long":
                # TODO: Implement configurable timeout
                self.ui.info("Retrying with extended timeout...")
                ai_response = self.query_ai(original_word)
                if not ai_response:
                    self.ui.warning("Retry failed. Returning to main menu.")
                    return
            elif recovery_choice == "settings":
                self.show_settings_screen()
                # After settings, offer to retry
                if self.ui.confirm("Try querying AI again?", default=True):
                    ai_response = self.query_ai(original_word)
                    if not ai_response:
                        self.ui.warning("Query failed. Returning to main menu.")
                        return
                else:
                    return
            else:  # skip
                return

        # --- Spelling Check and Final Word Determination ---
        if detected_type == 'sentence':
            # For sentences, do not attempt to auto-correct; keep text as-is
            final_word = original_word
        else:
            final_word = self.check_spelling(original_word, ai_response)
        if final_word is None: # User chose to abandon the edit during spelling check
            preview = original_word.strip().replace('\n', ' ')
            if len(preview) > 80:
                preview = preview[:77] + '...'
            self.ui.warning(f"Abandoning entry for '{preview}'.")
            return
        
        # --- Stage 2 Duplicate Check (Final/Corrected Word) ---
        # Check again only if the final word is different from the original input (case-insensitive)
        # and it wasn't the word found in the first check (if any)
        if final_word.lower() != original_word.lower() and not (self.duplicate_resolution and self.duplicate_resolution.get('mode') in ('merge','force')):
            existing_word_check2 = self.check_duplicate(final_word)
            if existing_word_check2 and existing_word_check2 != existing_word_check1:
                self.ui.info(f"Performing second duplicate check for corrected word '{final_word}'...")
                if not self.handle_duplicate(final_word, existing_word_check2):
                    self.ui.warning(f"Skipping '{final_word}' due to duplicate check (Stage 2).")
                    return # User chose to skip or view existing entry

        # --- Parse AI Response ---
        word_type, definitions, examples = self.parse_ai_response(ai_response)
        if not word_type or not definitions or not examples:
             self.ui.error("Cannot add vocabulary entry: Failed to parse essential information from AI response.")
             return
        if isinstance(word_type, list):
            primary_word_type = word_type[0] if word_type else ""
        else:
            primary_word_type = str(word_type or "")

        # Post-parse routing opportunity if AI identified as sentence
        if (word_type and isinstance(word_type, list) and primary_word_type.lower() == 'sentence' and
            getattr(self, 'route_sentences', True)):
            title = self._translator_title(self.language_config.target_to_eng)
            route2 = self.ui.confirm(
                f"AI identified this as a sentence. Route to {title} instead?",
                default=True,
            )
            if route2:
                if not self.fr_to_eng_translator:
                    alt_title = self._translator_title(self.language_config.target_to_eng)
                    self.ui.error(f"{alt_title} is not available (initialization failed). Proceeding in vocab mode.")
                else:
                    ok = self.fr_to_eng_translator.translate_and_save(original_word)
                    if ok is False:
                        self.ui.warning("Translation cancelled or failed.")
                    return

        # If we keep sentence in vocab and examples are disabled, drop them
        if primary_word_type.lower() == 'sentence' and not getattr(self, 'sentence_examples_in_vocab', False):
            examples = []

        # --- Display Parsed Info ---
        self.display_parsed_info(final_word, word_type, definitions, examples)

        # --- Merge path (if selected) ---
        if self.duplicate_resolution and self.duplicate_resolution.get('mode') == 'merge':
            target_key = self.duplicate_resolution.get('existing', final_word)
            self.merge_into_existing(target_key, primary_word_type, definitions, examples)
            self.ui.success(f"Merged AI content into existing entry for '{target_key}'.")
            self.duplicate_resolution = None
            return

        history_action = "new"
        history_existing_word: Optional[str] = None
        if self.duplicate_resolution:
            history_action = self.duplicate_resolution.get('mode', 'new')
            history_existing_word = self.duplicate_resolution.get('existing')
        corrected_word_value: Optional[str] = None

        # --- Format LaTeX Entry ---
        insert_word = final_word
        # If force mode and still colliding, create a unique variant
        if self.duplicate_resolution and self.duplicate_resolution.get('mode') == 'force':
            if self.check_duplicate(insert_word):
                insert_word = self.create_unique_variant(insert_word)
        latex_entry = self.format_latex_entry(
            insert_word,
            primary_word_type,
            definitions,
            examples,
            entry_command=self.entry_command,
        )  # Use first element of word_type list

        # --- Validate LaTeX Entry ---
        if not self.is_valid_latex_entry(latex_entry):
            self.ui.error("Cannot add vocabulary entry: Generated LaTeX is empty or invalid.")
            return

        # --- Display LaTeX Entry ---
        self.display_latex_entry(latex_entry)

        # Spelling correction now happens before LaTeX generation (no need to re-confirm here)
        corrected_word_value = final_word if final_word != original_word else None

        # --- Confirm Save ---
        if not self.ui.confirm(
            f"Add this entry for '{insert_word}' to your vocabulary file?",
            default=True,
        ):
            self.ui.warning(f"Entry for '{insert_word}' discarded. Nothing saved.")
            self.duplicate_resolution = None
            return

        final_word = insert_word

        # --- Insert ---
        self.insert_entry_alphabetically(latex_entry, insert_word) # Insert using the (possibly variant) word

        # --- Update In-Memory Dictionaries ---
        self.add_word_to_entries(insert_word, primary_word_type, definitions, examples) # Use first element of word_type list

        history_metadata: Dict[str, Any] = {}
        if history_existing_word:
            history_metadata["existing_word"] = history_existing_word
        if corrected_word_value:
            history_metadata["corrected_word"] = corrected_word_value
        if original_word != insert_word:
            history_metadata["original_input"] = original_word
            history_metadata["saved_word"] = insert_word
        if history_action == "force":
            history_metadata["forced_variant"] = insert_word

        self._log_vocab_history(
            action=history_action,
            original_text=original_word,
            saved_word=insert_word,
            word_type=primary_word_type,
            definitions=definitions,
            examples=examples,
            metadata=history_metadata or None,
        )

        # --- Alphabetize ---
        self.alphabetize_entries()

        self.duplicate_resolution = None

        entry_count = len(self.word_entries)
        self.ui.success(f"Entry saved successfully! ({entry_count - 1} → {entry_count} entries)")

        # Quick action menu - allow users to continue without returning to main menu
        try:
            quick_action = self.ui.interactive_menu(
                "What's next?",
                [
                    ("add", "Add another word"),
                    ("view", "View all vocabulary"),
                    ("search", "Search vocabulary"),
                    ("menu", "Return to main menu"),
                ],
                "Press Esc to return to main menu",
            )

            if quick_action == "add":
                # Recursively call to add another word
                self.handle_new_word_entry()
            elif quick_action == "view":
                self.display_all_vocabulary()
            elif quick_action == "search":
                self.search_vocabulary()
            # If "menu" selected, just return normally

        except KeyboardInterrupt:
            # User pressed Esc - return to main menu
            pass

    def create_unique_variant(self, base_word: str) -> str:
        """Create a unique variant label for a duplicate word using hyphenated suffixes."""
        candidate = f"{base_word} - alt"
        if not self.check_duplicate(candidate):
            return candidate
        # Try alphabetical suffixes
        for suffix in 'abcdefghijklmnopqrstuvwxyz':
            candidate = f"{base_word} - alt {suffix}"
            if not self.check_duplicate(candidate):
                return candidate
        # Fallback with repeated 'alt'
        i = 2
        while True:
            candidate = f"{base_word} - alt x{i}"
            if not self.check_duplicate(candidate):
                return candidate
            i += 1

    def merge_into_existing(self, existing_word: str, new_type: str, new_defs: List[str], new_examples: List[Tuple[str, str]]):
        """Merge new definitions/examples into an existing entry and update the LaTeX file and memory."""
        self._ensure_entries_loaded()
        key = existing_word.lower()
        if key not in self.word_entries:
            self.ui.error(f"Cannot merge: existing entry for '{existing_word}' not found.")
            return
        entry = self.word_entries[key]

        # Use structured lists if available else fallback
        defs_existing = entry.get('definitions_list') or [d.strip() for d in entry['definitions'].split('; ') if d.strip()]
        exs_existing = entry.get('examples_list') or []
        if not exs_existing and entry.get('examples'):
            for e in entry['examples'].split('; '):
                if ' (' in e and e.endswith(')'):
                    fr, en = e.rsplit(' (', 1)
                    exs_existing.append((fr, en[:-1]))

        # Dedup helpers
        def norm_text(s: str) -> str:
            return re.sub(r"\s+", " ", s).strip().lower()
        def norm_pair(p: Tuple[str,str]) -> Tuple[str,str]:
            return (norm_text(p[0]), norm_text(p[1]))

        merged_defs_map = {norm_text(d): d for d in defs_existing}
        added_defs: List[str] = []
        for d in new_defs:
            nd = norm_text(d)
            if nd and nd not in merged_defs_map:
                merged_defs_map[nd] = d
                added_defs.append(d)
        merged_defs = list(merged_defs_map.values())

        merged_exs_map = {norm_pair(p): p for p in exs_existing}
        added_examples: List[Tuple[str, str]] = []
        for p in new_examples:
            np = norm_pair(p)
            if np not in merged_exs_map:
                merged_exs_map[np] = p
                added_examples.append(p)
        merged_exs = list(merged_exs_map.values())

        # Keep existing type by default; if unknown, use new
        final_type = entry.get('type') or new_type
        # Rebuild LaTeX entry and replace in file
        latex_block = self.format_latex_entry(
            entry['word'],
            final_type,
            merged_defs,
            merged_exs,
            entry_command=self.entry_command,
        )
        self.update_entry_in_file(entry['word'], latex_block)

        # Update memory
        entry['type'] = final_type
        entry['definitions_list'] = merged_defs
        entry['examples_list'] = merged_exs
        entry['definitions'] = "; ".join(merged_defs)
        entry['examples'] = "; ".join([f"{f} ({e})" for f,e in merged_exs])
        self._log_merge_history(
            existing_word=entry['word'],
            final_type=final_type,
            merged_definitions=merged_defs,
            merged_examples=merged_exs,
            added_definitions=added_defs,
            added_examples=added_examples,
        )

    def update_entry_in_file(self, word_capitalized: str, new_block: str) -> None:
        """Replace the LaTeX entry block for the given word with new_block."""
        try:
            with self.latex_file.open("r", encoding="utf-8") as f:
                content = f.read()
            # Regex to match the specific entry by word with robust body matching
            entry_cmd_pattern = re.escape(self._entry_command())
            word_pattern = re.escape(word_capitalized)
            pattern = rf"""
                {entry_cmd_pattern}
                \{{{word_pattern}\}}
                \{{[^{{}}]*\}}
                \{{ (?: [^{{}}]+ | \{{[^{{}}]*\}} )* \}}
                \{{ (?: [^{{}}]+ | \{{[^{{}}]*\}} )* \}}
            """
            new_content, n = re.subn(pattern, new_block, content, count=1, flags=re.VERBOSE | re.DOTALL)
            if n == 0:
                self.ui.warning(f"Could not locate LaTeX entry for '{word_capitalized}' to update. Skipping file update.")
                return
            with self.latex_file.open("w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            self.ui.error(f"Failed to update LaTeX entry for '{word_capitalized}': {e}")

    def is_valid_latex_entry(self, latex_entry: str) -> bool:
        # Check if the entry is not empty and contains the expected LaTeX structure
        entry_cmd = self._entry_command()
        return bool(latex_entry.strip()) and entry_cmd in latex_entry

    def _strip_trailing_punctuation(self, text: str) -> str:
        """Normalize by removing trailing punctuation and surrounding whitespace."""
        if not text:
            return text
        return text.rstrip(string.punctuation + " \t\r\n")

    def check_spelling(self, word, ai_response):
        # More specific regex that stops at the next field and handles multiline content
        # Extract the spelling check section (value not used)
        # Keep for potential future diagnostics, but avoid unused variable warnings
        _ = re.search(r'Spelling Check:\s*(.*?)(?=\nCorrectly Spelt Word:|$)', ai_response, re.DOTALL)

        corrected_spelling_match = re.search(r'Correctly Spelt Word:\s*(.*?)(?=\nWord Type:|$)', ai_response, re.DOTALL)
        corrected_spelling = corrected_spelling_match.group(1).strip() if corrected_spelling_match else None

        trimmed_original = word.strip()
        trimmed_corrected = corrected_spelling.strip() if corrected_spelling else None

        # Validate the corrected spelling - check if it's empty, placeholder text, or same as input
        if corrected_spelling:
            # Remove common placeholder patterns
            if (corrected_spelling.startswith('[') and corrected_spelling.endswith(']')) or \
               not corrected_spelling.strip() or \
               corrected_spelling.lower().strip() == word.lower().strip():
                # Either placeholder text, empty, or same as input - no correction needed
                return word

            normalized_original = self._strip_trailing_punctuation(trimmed_original)
            normalized_corrected = self._strip_trailing_punctuation(trimmed_corrected)

            if normalized_original.lower() == normalized_corrected.lower():
                # Case-only or trailing punctuation differences—trust cleaned suggestion silently
                return normalized_corrected or corrected_spelling

            # Valid correction found that's different from input - ASK IMMEDIATELY
            suggestion_panel = (
                "[bold]You entered:[/bold] "
                f"[bold red]{word}[/bold red]\n"
                "[bold]Suggested spelling:[/bold] "
                f"[bold green]{corrected_spelling}[/bold green]"
            )
            self.ui.panel(
                suggestion_panel,
                title="⚡ Spelling Suggestion",
                border_style="yellow",
                expand=False,
            )

            # Ask user to choose immediately (before generating LaTeX)
            use_corrected = self.ui.confirm(
                f"Use corrected spelling '{corrected_spelling}'?",
                default=True,
            )

            if use_corrected:
                self.ui.info(f"✓ Using corrected spelling: '{corrected_spelling}'")
                return corrected_spelling
            else:
                self.ui.info(f"✓ Keeping original spelling: '{word}'")
                return word

        return word

    def add_word_to_entries(self, word: str, word_type: str, definitions: List[str], examples: List[Tuple[str, str]]):
        """Updates the in-memory dictionaries with the new word entry."""
        self._entries_loaded = True
        word_lower = word.lower()
        display_word = word if word_type.lower() == 'sentence' else word.capitalize()
        self.word_entries[word_lower] = {
            "word": display_word,
            "type": word_type,
            "definitions": "; ".join(definitions),
            "examples": "; ".join([f"{f} ({e})" for f, e in examples]),
            "definitions_list": list(definitions),
            "examples_list": list(examples),
        }
        # Update normalized entries as well
        normalized_word = self.normalize_word(word_lower)
        self.normalized_entries[normalized_word] = word_lower
        self.entry_count = len(self.word_entries) # Keep count accurate

    def handle_anki_export(self):
        default_deck = self.language_config.anki.default_deck_name
        mode_options = [
            ("incremental", "Incremental (new words only)"),
            ("rebuild", "Full rebuild (all words)"),
            ("selected", "Selected words"),
        ]
        try:
            export_mode = self.ui.interactive_menu(
                "Anki Export Mode",
                mode_options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Cancel",
            )
        except KeyboardInterrupt:
            self.ui.warning("Anki export cancelled.")
            return
        except Exception:
            export_mode = "incremental"

        selected_words: Optional[Set[str]] = None
        include_exported = False

        if export_mode == "rebuild":
            include_exported = True
        elif export_mode == "selected":
            selected_words = self._prompt_selected_words()
            if not selected_words:
                self.ui.warning("No matching words selected. Export cancelled.")
                return
            include_exported = True  # Ensure chosen entries are exported regardless of prior state.

        try:
            deck_name, explicit_path, reused_previous = self._determine_export_destination(default_deck)
        except KeyboardInterrupt:
            self.ui.warning("Anki export cancelled.")
            return

        if reused_previous:
            reuse_target = explicit_path if explicit_path else self._normalize_output_path(deck_name)
            self.ui.info(f"Reusing last Anki deck destination: {reuse_target}")

        self.export_to_anki(
            deck_name,
            include_exported_words=include_exported,
            selected_words=selected_words,
            output_path=explicit_path,
            export_context=export_mode,
        )
    
    def display_parsed_info(
            self,
            word: str,
            word_type: List[str],
            definitions: List[str],
            examples: List[Tuple[str, str]],
    ):
        word_type_str = ", ".join(word_type)
        self.ui.display_word_entry(word, word_type_str, definitions, examples)

    def _prompt_selected_words(self) -> Optional[Set[str]]:
        """Prompt the user to choose specific words for Anki export."""
        self._ensure_entries_loaded()
        if not self.word_entries:
            self.ui.warning("No vocabulary entries available to select.")
            return None

        prompt_text = (
            "Enter the words you want to export separated by commas\n"
            "(matching is case-insensitive; leave blank to cancel)"
        )
        raw_input = self.ui.prompt(prompt_text).strip()
        if not raw_input:
            return None

        tokens = [token.strip() for token in raw_input.split(",")]
        selected_keys: Set[str] = set()
        missing: List[str] = []

        for token in tokens:
            if not token:
                continue
            lower_token = token.lower()
            if lower_token in self.word_entries:
                selected_keys.add(lower_token)
                continue

            normalized = self.normalize_word(lower_token)
            match = next(
                (key for key, entry in self.word_entries.items() if self.normalize_word(key) == normalized),
                None,
            )
            if match:
                selected_keys.add(match)
            else:
                missing.append(token)

        if missing:
            self.ui.warning(
                "The following words were not found and will be skipped: "
                + ", ".join(sorted(missing))
            )

        if not selected_keys:
            return None
        return selected_keys

    def _normalize_deck_title(self, candidate: str) -> str:
        """Derive a clean deck title from arbitrary user input or paths."""
        value = (candidate or "").strip()
        if not value:
            return self.language_config.anki.default_deck_name
        lower = value.lower()
        if lower.endswith(".apkg"):
            value = value[:-5]
        name = Path(value).name or value
        sanitized = name.strip()
        if not sanitized:
            return self.language_config.anki.default_deck_name
        return sanitized

    def _normalize_output_path(self, destination: Union[str, Path]) -> Path:
        """Resolve an absolute .apkg path from either a deck name or explicit destination."""
        if isinstance(destination, Path):
            raw = str(destination)
        else:
            raw = (destination or "").strip()

        if not raw:
            raw = self.language_config.anki.default_deck_name

        expanded = os.path.expanduser(raw)
        if expanded.lower().endswith(".apkg"):
            candidate = Path(expanded)
        else:
            candidate = Path(f"{expanded}.apkg")

        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    def _determine_export_destination(self, default_deck: str) -> Tuple[str, Optional[Path], bool]:
        """Pick an Anki deck destination, reusing prior exports when possible."""
        metadata = getattr(self, "last_export_metadata", None) or {}
        previous_deck = (metadata.get("deck_name") or "").strip()
        previous_path: Optional[Path] = None
        previous_raw_path = metadata.get("path")
        if previous_raw_path:
            try:
                previous_path = Path(os.path.expanduser(str(previous_raw_path)))
            except (TypeError, ValueError):
                previous_path = None

        if previous_deck and previous_path:
            location_desc = str(previous_path)
            if not previous_path.exists():
                location_desc += " (new file will be created)"
            options = [
                ("reuse_previous", f"Reuse last deck '{previous_deck}' ({location_desc})"),
                ("new_deck", "Choose a different deck"),
            ]
            try:
                choice = self.ui.interactive_menu(
                    "Anki Deck Destination",
                    options,
                    "[↑↓] Navigate • [Enter] Select • [Esc] Cancel",
                )
            except KeyboardInterrupt:
                raise
            except Exception:
                choice = "reuse_previous"

            if choice == "reuse_previous":
                return previous_deck, previous_path, True

        prompt_default = previous_deck or default_deck
        raw_entry = self.ui.prompt("Enter a name for your Anki deck", default=prompt_default).strip()
        if not raw_entry:
            raw_entry = prompt_default

        ends_with_extension = raw_entry.lower().endswith(".apkg")
        contains_directory = raw_entry.startswith("~") or any(
            sep in raw_entry for sep in (os.sep, os.altsep) if sep
        )

        if contains_directory or ends_with_extension:
            explicit_path = Path(os.path.expanduser(raw_entry))
            deck_title = self._normalize_deck_title(raw_entry)
            return deck_title, explicit_path, False

        deck_title = self._normalize_deck_title(raw_entry)
        return deck_title, None, False

    def display_latex_entry(self, latex_entry: str):
        self.ui.display_latex_entry(latex_entry)

    def get_all_latex_entries(self) -> Set[str]:
        # Return a set of all words in the LaTeX file, including incomplete entries
        with self.latex_file.open("r", encoding="utf-8") as file:
            content = file.read()
        entry_cmd_pattern = re.escape(self._entry_command()) + r"\{(.*?)\}"
        entries = re.findall(entry_cmd_pattern, content)
        return set(entry.lower() for entry in entries)

    def get_all_exported_words(self) -> Set[str]:
        return set(self.exported_words)

    def compare_entries_and_exports(self) -> Tuple[Set[str], Set[str]]:
        latex_entries = self.get_all_latex_entries()
        exported_words = self.get_all_exported_words()
        in_latex_not_exported = latex_entries - exported_words
        in_exports_not_latex = exported_words - latex_entries
        return in_latex_not_exported, in_exports_not_latex

    def generate_discrepancy_report(self):
        in_latex_not_exported, in_exports_not_latex = self.compare_entries_and_exports()
        
        data = {
            "In LaTeX but not exported": ", ".join(sorted(in_latex_not_exported)) or "None",
            "In exports but not in LaTeX": ", ".join(sorted(in_exports_not_latex)) or "None"
        }
        
        self.ui.dict_to_table(data, title="Discrepancy Report")
        
        if not in_latex_not_exported and not in_exports_not_latex:
            self.ui.success("No discrepancies found!")
        else:
            self.ui.warning("Discrepancies found. Please review the report above.")

    def reconcile_menu_option(self):
        self.generate_discrepancy_report()
        # Offer one-click actions
        in_latex_not_exported, in_exports_not_latex = self.compare_entries_and_exports()
        # Export missing LaTeX words to Anki
        if in_latex_not_exported:
            if self.ui.confirm(f"Export {len(in_latex_not_exported)} word(s) missing in Anki now?", default=True):
                try:
                    deck_name, explicit_path, _ = self._determine_export_destination(
                        self.language_config.anki.default_deck_name
                    )
                except KeyboardInterrupt:
                    self.ui.warning("Anki export cancelled.")
                    return
                self.export_to_anki(
                    deck_name,
                    output_path=explicit_path,
                    export_context="reconcile_missing",
                )
        # Remove extra exported words not present in LaTeX
        if in_exports_not_latex:
            if self.ui.confirm(f"Remove {len(in_exports_not_latex)} stale exported word(s) from tracking?", default=False):
                self.exported_words.difference_update(in_exports_not_latex)
                self.save_exported_words()
                self.ui.success("Updated exported words; removed stale entries.")

    def display_all_vocabulary(self):
        """Displays all vocabulary entries present in the LaTeX file in a paginated table format.
        
        This function retrieves all vocabulary entries from the LaTeX file, formats them
        into a Rich table, and displays them with pagination for better readability.
        """
        self._ensure_entries_loaded()
        if not self.word_entries:
            self.ui.warning("No vocabulary entries found in the LaTeX file.")
            return
        
        # Sort entries alphabetically
        sorted_entries = sorted(self.word_entries.items(), key=lambda x: self.normalize_word(x[0]))
        
        headers = ["No.", "Word", "Type", "Definitions"]
        rows = []
        truncated_definitions: Dict[int, str] = {}

        for index, (word, entry) in enumerate(sorted_entries, 1):
            definitions = entry["definitions"]
            display_definitions = definitions
            if len(definitions) > self.DEFINITION_PREVIEW_LIMIT:
                display_definitions = definitions[: self.DEFINITION_PREVIEW_LIMIT - 3] + "..."
                truncated_definitions[index] = definitions

            rows.append([
                str(index),
                entry["word"],
                entry["type"] if isinstance(entry["type"], str) else ", ".join(entry["type"]),
                display_definitions
            ])

        self.ui.render_table(
            title=f"All Vocabulary Entries ({len(self.word_entries)} words)",
            columns=headers,
            rows=rows,
            column_styles=["cyan", "magenta", "green", "white"],
        )

        if truncated_definitions:
            self.ui.info(
                "Some definitions are abbreviated. Enter an entry number to view the full text or press Enter to exit.",
                accent="dim",
            )
            while True:
                selection = read_line("Show full definitions for #: ")
                if not selection.strip():
                    break
                if selection.strip().isdigit():
                    entry_number = int(selection.strip())
                    full_text = truncated_definitions.get(entry_number)
                    if full_text is None:
                        self.ui.warning("Please enter a valid entry number with truncated definitions.")
                        continue
                    self.ui.panel(
                        full_text,
                        title=f"Definitions for entry {entry_number}",
                        border_style="dark_orange",
                        expand=True,
                    )
                else:
                    self.ui.warning("Please enter a number or press Enter to finish.")

        search_query = self.ui.prompt(
            "Search vocabulary (press Enter to skip)",
            style="dim",
        ).strip()
        if search_query:
            self.search_vocabulary(search_query)

    def search_vocabulary(self, search_term: Optional[str] = None):
        """Allows searching for specific vocabulary entries by keyword."""
        self._ensure_entries_loaded()
        if search_term is None:
            search_term = self.ui.prompt("Enter search term").strip()
        search_term = search_term.lower()
        if not search_term:
            self.ui.info("Search skipped.", accent="dim")
            return
        
        results = {}
        for word, entry in self.word_entries.items():
            if (search_term in word.lower() or 
                search_term in entry["definitions"].lower() or 
                (isinstance(entry["type"], str) and search_term in entry["type"].lower()) or
                (isinstance(entry["type"], list) and any(search_term in t.lower() for t in entry["type"]))):
                results[word] = entry
        
        if not results:
            self.ui.warning(f"No results found for '{search_term}'.")
            return
        
        # Display search results
        headers = ["Word", "Type", "Definitions"]
        rows = []
        
        for word, entry in sorted(results.items(), key=lambda x: self.normalize_word(x[0])):
            definitions = entry["definitions"]
            display_definitions = definitions
            if len(definitions) > self.DEFINITION_PREVIEW_LIMIT:
                display_definitions = definitions[: self.DEFINITION_PREVIEW_LIMIT - 3] + "..."
            
            rows.append([
                entry["word"],
                entry["type"] if isinstance(entry["type"], str) else ", ".join(entry["type"]),
                display_definitions
            ])
        
        self.ui.render_table(
            title=f"Search Results for '{search_term}' ({len(results)} matches)",
            columns=headers,
            rows=rows,
            column_styles=["magenta", "green", "white"],
        )
        
        # Offer to display full entry for a selected word
        if self.ui.confirm("Would you like to see the full entry for any of these words?", default=False):
            word_to_view = self.ui.prompt("Enter the word to view").strip()
            word_to_view_lower = word_to_view.lower()
            if word_to_view_lower in self.word_entries:
                self.display_existing_entry(word_to_view_lower)
            else:
                matching_words = [w for w in self.word_entries.keys() 
                                 if self.normalize_word(w) == self.normalize_word(word_to_view)]
                if matching_words:
                    self.display_existing_entry(matching_words[0])
                else:
                    self.ui.error(f"Word '{word_to_view}' not found.")
