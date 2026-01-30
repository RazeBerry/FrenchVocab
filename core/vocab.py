import json
import os
import re
import shutil
import string
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from pathlib import Path
from rich.console import Console
from enum import Enum, auto
from cli.menu import main_menu_loop
from anki_exporter import latex_to_anki_format as latex_to_anki_html
from ai_response_parser import parse_ai_response_text
import time
import threading
from languages import LanguageConfig, TranslatorConfig, default_language_code, get_language_config
from typing import TYPE_CHECKING

from .history_logger import TranslationLogger
from .vocab_repository import VocabRepository, EntryNotFoundError
from .llm_coordinator import LLMCoordinator
from .anki_manager import AnkiExportManager
from .spelling_checker import SpellingChecker
from .word_entry_workflow import WordEntryWorkflow
from models import normalize_word_key
from ui_helper import UIHelper, read_line
from core.providers.manager import (
    ProviderManager,
    ProviderMetadata,
)

if TYPE_CHECKING:  # pragma: no cover - optional provider clients
    from llm_client import GeminiClient  # noqa: F401
    from .translator import TranslatorCLI  # noqa: F401
    from .auto_translator import AutoTranslator  # noqa: F401

class WordType(Enum):
    NOUN = auto()
    VERB = auto()
    ADJECTIVE = auto()
    ADVERB = auto()
    EXPRESSION = auto()
    PRONOMINAL_VERB = auto()
    OTHER = auto()


class _TestDoubleVocabRepoAdapter:
    """Adapter to make test doubles work with AnkiExportManager.

    Test doubles created via object.__new__() set word_entries directly on the
    builder. This adapter wraps the builder to provide the VocabRepository
    interface that AnkiExportManager expects.
    """

    def __init__(self, builder: "FrenchVocabBuilder"):
        self._builder = builder

    @property
    def word_entries(self) -> Dict[str, Any]:
        return getattr(self._builder, "word_entries", {})

    def ensure_entries_loaded(self) -> None:
        pass  # Test doubles set word_entries directly

    def normalize_word(self, word: str) -> str:
        # Simple normalization for test doubles
        import unicodedata
        normalized = unicodedata.normalize("NFD", word.lower())
        return "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    def get_all_latex_entries(self) -> Set[str]:
        return set(self.word_entries.keys())


class FrenchVocabBuilder:
    DEFAULT_LANGUAGE_CONFIG = get_language_config(None)
    DEFAULT_LANGUAGE_CODE = default_language_code()
    DEFAULT_FILENAME = DEFAULT_LANGUAGE_CONFIG.vocab_filename
    language_config: LanguageConfig = DEFAULT_LANGUAGE_CONFIG
    language_code: str = DEFAULT_LANGUAGE_CODE
    DEFINITION_PREVIEW_LIMIT = 60

    def __getattribute__(self, name):
        # Delegate word_entries and normalized_entries to _vocab_repo
        if name in {"word_entries", "normalized_entries"}:
            try:
                vocab_repo = object.__getattribute__(self, "_vocab_repo")
                vocab_repo.ensure_entries_loaded()
                return getattr(vocab_repo, name)
            except AttributeError:
                # Fallback for test doubles using object.__new__()
                # Check if the attribute was set directly on the instance (test double pattern)
                try:
                    return object.__getattribute__(self, name)
                except AttributeError:
                    # Fail explicitly - don't silently create empty dicts
                    raise RuntimeError(
                        f"Cannot access {name}: VocabRepository not initialized. "
                        f"Ensure FrenchVocabBuilder is properly constructed or use "
                        f"the test double pattern by setting {name} directly on the instance."
                    )
        return object.__getattribute__(self, name)

    def _ensure_anki_manager(self) -> "AnkiExportManager":
        """Return the AnkiExportManager, creating one for test doubles if needed.

        Test doubles created via object.__new__() bypass __init__ and don't have
        _anki. This method lazily creates a minimal AnkiExportManager using
        attributes set directly on the test double.
        """
        if hasattr(self, "_anki"):
            return self._anki

        # Create AnkiExportManager for test double
        from tempfile import gettempdir

        # Get or create exported_words_file
        exported_words_file = getattr(self, "_exported_words_file_fallback", None)
        if exported_words_file is None:
            exported_words_file = Path(gettempdir()) / "test_exported_words.json"

        # Use default language config if not set
        lang_config = getattr(self, "language_config", self.DEFAULT_LANGUAGE_CONFIG)

        # Create adapter for test double's word_entries
        vocab_adapter = _TestDoubleVocabRepoAdapter(self)

        # Create minimal AnkiExportManager
        project_root = getattr(self, "project_root", Path(gettempdir()))
        anki_manager = AnkiExportManager(
            ui=self.ui,
            language_config=lang_config,
            vocab_repo=vocab_adapter,  # type: ignore[arg-type]
            exported_words_file=exported_words_file,
            project_root=project_root,
        )

        # Sync any state already set on the test double
        if hasattr(self, "_exported_words_fallback"):
            anki_manager.exported_words = self._exported_words_fallback
        if hasattr(self, "_exported_deck_version_fallback"):
            anki_manager.exported_deck_version = self._exported_deck_version_fallback

        # Cache for future calls
        object.__setattr__(self, "_anki", anki_manager)
        return anki_manager

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

        # Create vocab repository (handles LaTeX persistence)
        # Note: We create a temporary one first to check/create the file
        if not self.latex_file.exists():
            # Create file before initializing repository
            temp_repo = VocabRepository(
                latex_file=self.latex_file,
                entry_command=self.entry_command,
                language_config=self.language_config,
                ui=self.ui,
                vocab_template=self.vocab_template,
            )
            temp_repo.create_initial_tex_file()

        # Initialize the main vocab repository
        self._vocab_repo = VocabRepository(
            latex_file=self.latex_file,
            entry_command=self.entry_command,
            language_config=self.language_config,
            ui=self.ui,
            vocab_template=self.vocab_template,
        )

        # Backward compatibility: expose repo directly
        self.repo = self._vocab_repo.repo

        # Allow longer phrases before triggering the length check
        self.max_word_length = 1000  # default max characters (overridable)
        self.max_words: Optional[int] = None  # unlimited by default; overridable
        self.allow_sentence_punctuation: bool = True  # allow punctuation by default
        self.route_sentences: bool = True  # default: route sentences to Fr->En translator
        self.sentence_examples_in_vocab: bool = False  # default: omit examples for sentences
        self.config_file = "vocab_builder_config.json"
        self._config_data: Dict[str, Any] = {}
        self.history_logger: Optional[TranslationLogger] = None
        self._warmup_threads: List[threading.Thread] = []
        self._last_warmup_error: Optional[str] = None
        
        # Apply optional runtime settings (env/config overrides)
        self._load_input_limits()
        self.history_logger = self._create_history_logger()

        # Initialize translator attribute
        self.eng_to_fr_translator: Optional["TranslatorCLI"] = None
        self.fr_to_eng_translator: Optional["TranslatorCLI"] = None
        self.auto_translator: Optional["AutoTranslator"] = None
        self.duplicate_resolution: Optional[Dict[str, str]] = None  # stores {'mode': 'merge'|'force', 'existing': <word>}
        self.enable_auto_translator: bool = self._should_enable_auto_translator()

        # Create spelling checker (used by word entry workflow)
        self._spelling_checker = SpellingChecker(self.ui)

        self.eager_provider = eager_provider or (provider is not None)

        # Determine provider early and set verbosity before key bootstrapping
        requested_provider = provider or ProviderFactory.default_provider()
        provider_metadata: ProviderMetadata = self.provider_manager.get_metadata(requested_provider)

        # Create LLM coordinator (handles provider lifecycle, queries, usage tracking)
        load_config_start = time.time()
        self._llm = LLMCoordinator(
            ui=self.ui,
            provider_manager=self.provider_manager,
            provider_metadata=provider_metadata,
            verbose=verbose,
            client=client,
            eager=self.eager_provider,
        )
        # Register callback to clear translators when entering degraded mode
        self._llm.set_degraded_mode_callback(self._on_llm_degraded)
        # Register callback to initialize translators when client becomes ready
        self._llm.set_client_ready_callback(self._init_translators)
        load_config_end = time.time()

        # Defer LaTeX parsing until first use to reduce startup time for large libraries.

        # Create Anki export manager (handles export workflows, tracking)
        exported_words_file = self._resolve_exported_words_path(project_root, self.latex_file.parent)
        self._anki = AnkiExportManager(
            ui=self.ui,
            language_config=self.language_config,
            vocab_repo=self._vocab_repo,
            exported_words_file=exported_words_file,
            project_root=project_root,
        )
        # entry_count is now a property that delegates to _vocab_repo
        
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

    # -------------------------------------------------------------------------
    # LLM Coordinator Delegation (backward compatibility)
    # -------------------------------------------------------------------------

    def _on_llm_degraded(self, reason: str) -> None:
        """Callback invoked by LLMCoordinator when entering degraded mode."""
        self.eng_to_fr_translator = None
        self.fr_to_eng_translator = None
        self.auto_translator = None

    @property
    def client(self):
        """The active LLM client (delegated to LLMCoordinator)."""
        return self._llm.client

    @client.setter
    def client(self, value):
        self._llm.client = value

    @property
    def api_available(self) -> bool:
        """Whether the AI provider is available (delegated to LLMCoordinator)."""
        return self._llm.api_available

    @api_available.setter
    def api_available(self, value: bool):
        self._llm.api_available = value

    @property
    def api_error_reason(self) -> Optional[str]:
        """Reason for API unavailability (delegated to LLMCoordinator)."""
        return self._llm.api_error_reason

    @api_error_reason.setter
    def api_error_reason(self, value: Optional[str]):
        self._llm.api_error_reason = value

    @property
    def entry_count(self) -> int:
        """Live count of vocabulary entries (delegated to VocabRepository)."""
        if hasattr(self, "_vocab_repo") and self._vocab_repo is not None:
            return self._vocab_repo.entry_count
        return int(getattr(self, "_entry_count_fallback", 0) or 0)

    @entry_count.setter
    def entry_count(self, value: int) -> None:
        """Allow callers to cache a fast count without forcing a full parse.

        Some startup paths compute an approximate count via regex scanning
        (see VocabRepository.count_entries) and store it for UI display.
        """
        count = int(value or 0)
        if hasattr(self, "_vocab_repo") and self._vocab_repo is not None:
            self._vocab_repo.entry_count = count
            return
        object.__setattr__(self, "_entry_count_fallback", count)

    @property
    def provider(self) -> str:
        """The active provider identifier (delegated to LLMCoordinator)."""
        return self._llm.provider

    @provider.setter
    def provider(self, value: str) -> None:
        """Set the provider identifier (updates coordinator metadata)."""
        # For backward compatibility in tests - update metadata identifier
        if hasattr(self._llm, '_provider_metadata'):
            # Create a modified metadata with the new identifier
            from core.providers.manager import ProviderMetadata
            old_meta = self._llm._provider_metadata
            self._llm._provider_metadata = ProviderMetadata(
                identifier=value,
                display_name=old_meta.display_name,
                env_var=old_meta.env_var,
                keyring_name=old_meta.keyring_name,
            )

    @property
    def provider_metadata(self) -> ProviderMetadata:
        """Full metadata for the active provider (delegated to LLMCoordinator)."""
        return self._llm.provider_metadata

    @provider_metadata.setter
    def provider_metadata(self, value: ProviderMetadata):
        self._llm.provider_metadata = value

    @property
    def verbose(self) -> bool:
        """Whether verbose output is enabled (delegated to LLMCoordinator)."""
        return self._llm.verbose

    @verbose.setter
    def verbose(self, value: bool):
        self._llm.verbose = value

    @property
    def session_usage(self) -> Dict[str, int]:
        """Session token usage statistics (delegated to LLMCoordinator)."""
        return self._llm.session_usage

    @property
    def session_requests(self) -> int:
        """Number of AI requests in this session (delegated to LLMCoordinator)."""
        return self._llm.session_requests

    @property
    def _llm_thread(self):
        """Background LLM initialization thread (delegated to LLMCoordinator)."""
        return self._llm.llm_thread

    # -------------------------------------------------------------------------
    # Anki Export Manager Delegation (backward compatibility)
    # -------------------------------------------------------------------------

    @property
    def exported_words(self) -> Set[str]:
        """Set of exported words (delegated to AnkiExportManager)."""
        if hasattr(self, "_anki"):
            return self._anki.exported_words
        return getattr(self, "_exported_words_fallback", set())

    @exported_words.setter
    def exported_words(self, value: Set[str]):
        if hasattr(self, "_anki"):
            self._anki.exported_words = value
        else:
            # Fallback for test doubles without _anki
            object.__setattr__(self, "_exported_words_fallback", value)

    @property
    def exported_deck_version(self) -> Optional[str]:
        """Deck template version (delegated to AnkiExportManager)."""
        if hasattr(self, "_anki"):
            return self._anki.exported_deck_version
        return getattr(self, "_exported_deck_version_fallback", None)

    @exported_deck_version.setter
    def exported_deck_version(self, value: Optional[str]):
        if hasattr(self, "_anki"):
            self._anki.exported_deck_version = value
        else:
            object.__setattr__(self, "_exported_deck_version_fallback", value)

    @property
    def last_export_metadata(self) -> Optional[Dict[str, Any]]:
        """Last export metadata (delegated to AnkiExportManager)."""
        if hasattr(self, "_anki"):
            return self._anki.last_export_metadata
        return getattr(self, "_last_export_metadata_fallback", None)

    @last_export_metadata.setter
    def last_export_metadata(self, value: Optional[Dict[str, Any]]):
        if hasattr(self, "_anki"):
            self._anki.last_export_metadata = value
        else:
            object.__setattr__(self, "_last_export_metadata_fallback", value)

    @property
    def exported_words_file(self) -> Path:
        """Exported words tracking file path (delegated to AnkiExportManager)."""
        if hasattr(self, "_anki"):
            return self._anki.exported_words_file
        fallback = getattr(self, "_exported_words_file_fallback", None)
        return Path(fallback) if fallback else Path(".")

    @exported_words_file.setter
    def exported_words_file(self, value):
        # For test doubles - store as fallback
        if isinstance(value, str):
            value = Path(value)
        object.__setattr__(self, "_exported_words_file_fallback", value)

    def _init_translators(self) -> None:
        """Instantiate translator flows when an LLM client is available."""
        if not self.client:
            self.eng_to_fr_translator = None
            self.fr_to_eng_translator = None
            self.auto_translator = None
            return
        from .translator import TranslatorCLI

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
        from .auto_translator import AutoTranslator

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
            verbose=self.verbose,
        )

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

    def ensure_llm_ready(self) -> bool:
        """Ensure the LLM client is available (delegated to LLMCoordinator)."""
        return self._llm.ensure_ready(on_settings=self.show_settings_screen)

    def reconfigure_provider(self) -> bool:
        """Run provider setup again (delegated to LLMCoordinator)."""
        return self._llm.reconfigure(on_success=self._init_translators)

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
        """Human-readable provider label (delegated to LLMCoordinator)."""
        return self._llm.provider_label

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
        """Load exported words (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager().load_exported_words()

    def save_exported_words(self):
        """Save exported words (delegated to AnkiExportManager)."""
        self._ensure_anki_manager().save_exported_words()

    def count_entries(self) -> int:
        """Count entries with file stat caching for performance."""
        return self._vocab_repo.count_entries()

    def _ensure_entries_loaded(self) -> None:
        """Load LaTeX entries on first access to avoid startup penalty."""
        # Delegate to VocabRepository if available
        if hasattr(self, "_vocab_repo"):
            self._vocab_repo.ensure_entries_loaded()
            return
        # Fallback for test doubles without _vocab_repo
        if getattr(self, "_entries_loaded", False):
            return

    def load_existing_entries(self):
        """Load existing vocabulary entries using a balanced-brace parser."""
        # Delegate to VocabRepository if available
        if hasattr(self, "_vocab_repo"):
            self._vocab_repo.load_existing_entries()
            return
        # Fallback for test doubles - this path should rarely be hit
        pass

    def normalize_word(self, word: str) -> str:
        """Normalize a given word by converting it to lowercase and removing accents."""
        if hasattr(self, "_vocab_repo"):
            return self._vocab_repo.normalize_word(word)
        # Fallback for test doubles
        normalized = unicodedata.normalize("NFD", word.lower())
        return "".join(c for c in normalized if unicodedata.category(c) != "Mn")

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
        """Export vocabulary to Anki deck (delegated to AnkiExportManager)."""
        self._ensure_anki_manager().export_to_anki(
            deck_name=deck_name,
            include_exported_words=include_exported_words,
            selected_words=selected_words,
            auto_retry_on_empty=auto_retry_on_empty,
            output_path=output_path,
            export_context=export_context,
        )

    def check_duplicate(self, word: str) -> Optional[str]:
        """Check if a word already exists (returns existing key if duplicate)."""
        return self._vocab_repo.check_duplicate(word)

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
        # Alphabetize entries on launch to ensure consistent ordering.
        # This also fixes any unsorted state from previous Ctrl+C exits.
        try:
            self.alphabetize_entries(silent=True)
        except Exception:
            pass  # Non-critical; continue even if alphabetization fails

        # Determine provider name using state machine
        from core.llm_coordinator import InitState
        state = self._llm.init_state

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
            # Use state machine for clean status
            if state == InitState.IN_PROGRESS:
                provider_name = f"{provider_name} (initializing)"
            elif state == InitState.DEFERRED:
                provider_name = f"{provider_name} (init deferred)"
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
        eng_fr_count = 0
        if self.eng_to_fr_translator:
            eng_fr_count = self.eng_to_fr_translator.entry_count

        fr_eng_count = 0
        if self.fr_to_eng_translator:
            fr_eng_count = self.fr_to_eng_translator.entry_count

        exported_count = len(getattr(self, "exported_words", []))
        language_name = self.language_config.display_name

        # Display status summary panel above menu for reduced cognitive load
        # Use the state machine for clean, unambiguous status
        from core.llm_coordinator import InitState
        state = self._llm.init_state

        if state == InitState.READY:
            provider_status = "✓ Connected"
            provider_color = "green"
        elif state == InitState.IN_PROGRESS:
            provider_status = "⏳ Initializing"
            provider_color = "yellow"
        elif state == InitState.DEFERRED:
            provider_status = "⏳ Deferred"
            provider_color = "yellow"
        else:  # FAILED or NOT_STARTED
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
        """Display Anki submenu (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager().show_anki_menu()

    def handle_anki_tools(self) -> bool:
        """Route Anki workflows (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager().handle_anki_tools()

    def get_word_input(self) -> str:
        """Read target-language text from the user.

        Instructions:
        - Type or paste your text, then press Enter to submit.
        - Press Esc to cancel.
        """
        language_name = self.language_config.display_name
        limit_descriptors: list[str] = []
        if getattr(self, "max_words", None):
            limit_descriptors.append(f"≤{self.max_words} words")
        if getattr(self, "max_word_length", None):
            limit_descriptors.append(f"≤{self.max_word_length} chars")
        limit_hint = f" [{' • '.join(limit_descriptors)}]" if limit_descriptors else ""

        prompt = f"\nEnter {language_name} text{limit_hint} (Esc to cancel): "

        try:
            line = read_line(prompt)
        except EOFError:
            self.ui.warning("Input cancelled. Returning to main menu.")
            return ""
        except KeyboardInterrupt:
            self.ui.warning("Input cancelled. Returning to main menu.")
            return ""

        # Treat any ESC sequence as an immediate cancel
        if line and "\x1b" in line:
            self.ui.warning("Input cancelled via Esc. Returning to main menu.")
            return ""

        word = line.strip()

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
        """Query AI for vocabulary definition (uses LLMCoordinator for streaming)."""
        detected_type = self.detect_input_type(word)
        config = getattr(self, "language_config", self.DEFAULT_LANGUAGE_CONFIG)
        prompt_template = getattr(config, "prompt_template", None) or self.DEFAULT_LANGUAGE_CONFIG.prompt_template
        prompt = prompt_template.format(input_text=word, detected_type=detected_type)

        def _on_exception(exc: Exception, label: str) -> bool:
            return self._handle_ai_exception(exc, label)

        response, _ = self._llm.query(
            prompt=prompt,
            progress_label=self._provider_label(),
            on_exception=_on_exception,
        )
        return response

    def _handle_ai_exception(self, exc: Exception, provider_label: str) -> bool:
        """Handle AI provider failures (delegated to LLMCoordinator)."""
        return self._llm.handle_ai_exception(
            exc=exc,
            provider_label=provider_label,
            on_settings=self.show_settings_screen,
            on_switch_success=self._init_translators,
        )

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
        """Format word information into a LaTeX entry. Delegates to VocabRepository."""
        return VocabRepository.format_latex_entry(word, word_type, definitions, examples, entry_command)

    def insert_entry_alphabetically(self, new_entry: str, new_word: str) -> None:
        """Insert a new LaTeX entry at the appropriate position."""
        self._vocab_repo.insert_entry_alphabetically(new_entry, new_word)

    def alphabetize_entries(self, *, silent: bool = False) -> None:
        """Alphabetize the entries in the LaTeX file."""
        self._vocab_repo.alphabetize_entries(silent=silent)

    def exit_screen(self):
        # Best-effort alphabetization on clean exit
        try:
            self.alphabetize_entries(silent=True)
        except Exception:
            pass  # Non-critical; proceed with exit

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
        """Aggregate per-session token usage (delegated to LLMCoordinator)."""
        self._llm.record_usage(usage)

    def _format_token_summary(self) -> str:
        """Format session token usage (delegated to LLMCoordinator)."""
        return self._llm.format_token_summary()

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
                    import keyring  # type: ignore[import]
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
        """Allow user to switch between providers (delegated to LLMCoordinator)."""
        self._llm.change_provider_interactive(on_success=self._init_translators)

    def _update_api_key_interactive(self):
        """Allow user to update their API key (delegated to LLMCoordinator)."""
        self._llm.update_api_key_interactive(on_success=self._init_translators)

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
        """Handle the word entry flow by delegating to WordEntryWorkflow.

        This method creates a workflow instance and executes it, then handles
        the quick action menu for continued interaction.
        """
        # Create workflow with current state
        workflow = WordEntryWorkflow(
            vocab_repo=self._vocab_repo,
            llm=self._llm,
            ui=self.ui,
            language_config=self.language_config,
            history_logger=self.history_logger,
            spelling_checker=self._spelling_checker,
            fr_to_eng_translator=self.fr_to_eng_translator,
            max_word_length=self.max_word_length,
            max_words=self.max_words,
            allow_sentence_punctuation=self.allow_sentence_punctuation,
            route_sentences=self.route_sentences,
            sentence_examples_in_vocab=self.sentence_examples_in_vocab,
            entry_command=self.entry_command,
            provider_label_fn=self._provider_label,
            on_settings=self.show_settings_screen,
            get_word_input_fn=self.get_word_input,
            # Pass builder methods as callbacks for test compatibility
            query_ai_fn=self.query_ai,
            check_spelling_fn=self.check_spelling,
            parse_ai_response_fn=self.parse_ai_response,
            check_duplicate_fn=self.check_duplicate,
            display_parsed_info_fn=self.display_parsed_info,
            display_latex_entry_fn=self.display_latex_entry,
            is_valid_latex_entry_fn=self.is_valid_latex_entry,
            insert_entry_alphabetically_fn=self.insert_entry_alphabetically,
            add_word_to_entries_fn=self.add_word_to_entries,
        )

        # Run the workflow
        saved = workflow.run(self.ensure_llm_ready)

        # Sync duplicate_resolution state back
        self.duplicate_resolution = workflow.duplicate_resolution

        if not saved:
            return

        # Quick action menu - allow users to continue without returning to main menu
        self._show_word_entry_quick_actions()

    def _show_word_entry_quick_actions(self) -> None:
        """Show quick action menu after successful word entry."""
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

    def _show_post_translation_menu(self) -> None:
        """Show quick action menu after successful sentence translation."""
        try:
            quick_action = self.ui.interactive_menu(
                "What's next?",
                [
                    ("translate", "Translate another sentence"),
                    ("add", "Add a vocabulary word"),
                    ("menu", "Return to main menu"),
                ],
                "Press Esc to return to main menu",
            )

            if quick_action == "translate":
                # Go to translation menu
                translation_choice = self.show_translation_menu()
                if translation_choice == "auto" and self.auto_translator:
                    if self.ensure_llm_ready():
                        self.auto_translator.run()
                elif translation_choice == "eng_to_target" and self.eng_to_fr_translator:
                    if self.ensure_llm_ready():
                        self.eng_to_fr_translator.run()
                elif translation_choice == "target_to_eng" and self.fr_to_eng_translator:
                    if self.ensure_llm_ready():
                        self.fr_to_eng_translator.run()
            elif quick_action == "add":
                self.handle_new_word_entry()
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

    def merge_into_existing(self, existing_word: str, new_type: str, new_defs: List[str], new_examples: List[Tuple[str, str]]) -> bool:
        """Merge new definitions/examples into an existing entry.

        Delegates core merge logic to VocabRepository while handling history logging.
        Falls back to inline implementation for test doubles without _vocab_repo.

        Returns:
            True if merge was successful, False otherwise.
        """
        # Get entry state before merge for history logging
        self._ensure_entries_loaded()
        key = existing_word.lower()
        entry = self.word_entries.get(key)
        if not entry:
            self.ui.error(f"Cannot merge: existing entry for '{existing_word}' not found.")
            return False

        # Delegate to repository if available
        if hasattr(self, "_vocab_repo"):
            success = self._vocab_repo.merge_into_existing(existing_word, new_type, new_defs, new_examples)
            if success:
                updated_entry = self.word_entries.get(key, {})
                self._log_merge_history(
                    existing_word=updated_entry.get('word', existing_word),
                    final_type=updated_entry.get('type', new_type),
                    merged_definitions=updated_entry.get('definitions_list', new_defs),
                    merged_examples=updated_entry.get('examples_list', []),
                    added_definitions=new_defs,
                    added_examples=new_examples,
                )
            return success

        # Fallback for test doubles without _vocab_repo
        # Use structured lists if available else fallback with robust parsing
        defs_existing = entry.get('definitions_list') or [
            d.strip() for d in entry['definitions'].split('; ') if d.strip()
        ]
        exs_existing = entry.get('examples_list') or []
        if not exs_existing and entry.get('examples'):
            exs_existing = self._parse_examples_string(entry['examples'])

        # Dedup helpers with accent normalization
        def norm_text(s: str) -> str:
            text = re.sub(r"\s+", " ", s).strip().lower()
            return normalize_word_key(text)

        def norm_pair(p: Tuple[str, str]) -> Tuple[str, str]:
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

        final_type = entry.get('type') or new_type

        # Rebuild LaTeX entry
        latex_block = self.format_latex_entry(
            entry['word'],
            final_type,
            merged_defs,
            merged_exs,
            entry_command=self.entry_command,
        )

        # Try to update file first (transactional - allows tests to mock failures)
        try:
            self.update_entry_in_file(entry['word'], latex_block)
        except EntryNotFoundError as e:
            self.ui.error(f"Merge failed: {e}", with_panel=True)
            return False
        except IOError as e:
            self.ui.error(f"Merge failed - file I/O error: {e}", with_panel=True)
            return False

        # File updated successfully (or no real file in test double), update memory
        entry['type'] = final_type
        entry['definitions_list'] = merged_defs
        entry['examples_list'] = merged_exs
        entry['definitions'] = "; ".join(merged_defs)
        entry['examples'] = "; ".join([f"{f} ({e})" for f, e in merged_exs])

        self._log_merge_history(
            existing_word=entry['word'],
            final_type=final_type,
            merged_definitions=merged_defs,
            merged_examples=merged_exs,
            added_definitions=added_defs,
            added_examples=added_examples,
        )
        return True

    def _parse_examples_string(self, examples_str: str) -> List[Tuple[str, str]]:
        """Parse examples string into (source, translation) tuples.

        Delegates to repository if available, otherwise uses inline fallback for test doubles.
        """
        if hasattr(self, "_vocab_repo"):
            return self._vocab_repo._parse_examples_string(examples_str)
        # Fallback for test doubles without _vocab_repo
        result: List[Tuple[str, str]] = []
        if not examples_str:
            return result
        for example in examples_str.split('; '):
            example = example.strip()
            if not example:
                continue
            parsed = self._extract_translation_from_parens(example)
            if parsed:
                result.append(parsed)
            else:
                # Emit warning for malformed entries (matching repository behavior)
                if hasattr(self, "ui"):
                    self.ui.warning(f"Could not parse example translation: '{example[:50]}...'")
                result.append((example, ""))
        return result

    def _extract_translation_from_parens(self, text: str) -> Optional[Tuple[str, str]]:
        """Extract (source, translation) from 'source text (translation)' format.

        Delegates to repository if available, otherwise uses inline fallback for test doubles.
        """
        if hasattr(self, "_vocab_repo"):
            return self._vocab_repo._extract_translation_from_parens(text)
        # Fallback for test doubles without _vocab_repo
        text = text.rstrip()
        if not text.endswith(')'):
            return None
        depth = 0
        for i in range(len(text) - 1, -1, -1):
            if text[i] == ')':
                depth += 1
            elif text[i] == '(':
                depth -= 1
                if depth == 0:
                    source = text[:i].rstrip()
                    translation = text[i + 1:-1]
                    if source:
                        return (source, translation)
                    return None
        return None

    def update_entry_in_file(self, word_capitalized: str, new_block: str) -> None:
        """Replace the LaTeX entry block for the given word with new_block."""
        self._vocab_repo.update_entry_in_file(word_capitalized, new_block)

    def is_valid_latex_entry(self, latex_entry: str) -> bool:
        """Check if the entry contains expected LaTeX structure."""
        return self._vocab_repo.is_valid_latex_entry(latex_entry)

    def _strip_trailing_punctuation(self, text: str) -> str:
        """Normalize by removing trailing punctuation and surrounding whitespace."""
        if not text:
            return text
        return text.rstrip(string.punctuation + " \t\r\n")

    def check_spelling(self, word, ai_response):
        """Check spelling and prompt for correction. Delegates to SpellingChecker."""
        return self._spelling_checker.check(word, ai_response)

    def add_word_to_entries(self, word: str, word_type: str, definitions: List[str], examples: List[Tuple[str, str]]):
        """Update the in-memory dictionaries with a new word entry."""
        self._vocab_repo.add_word_to_entries(word, word_type, definitions, examples)

    def handle_anki_export(self):
        """Handle Anki export workflow (delegated to AnkiExportManager)."""
        self._ensure_anki_manager().handle_anki_export()

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
        """Prompt for word selection (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager()._prompt_selected_words()

    def _normalize_deck_title(self, candidate: str) -> str:
        """Normalize deck title (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager()._normalize_deck_title(candidate)

    def _normalize_output_path(self, destination: Union[str, Path]) -> Path:
        """Normalize output path (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager()._normalize_output_path(destination)

    def _determine_export_destination(self, default_deck: str) -> Tuple[str, Optional[Path], bool]:
        """Determine export destination (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager()._determine_export_destination(default_deck)

    def display_latex_entry(self, latex_entry: str):
        self.ui.display_latex_entry(latex_entry)

    def get_all_latex_entries(self) -> Set[str]:
        """Return a set of all words in the LaTeX file."""
        return self._vocab_repo.get_all_latex_entries()

    def get_all_exported_words(self) -> Set[str]:
        """Get all exported words (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager().get_all_exported_words()

    def compare_entries_and_exports(self) -> Tuple[Set[str], Set[str]]:
        """Compare entries and exports (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager().compare_entries_and_exports()

    def generate_discrepancy_report(self):
        """Generate discrepancy report (delegated to AnkiExportManager)."""
        self._ensure_anki_manager().generate_discrepancy_report()

    def reconcile_menu_option(self):
        """Reconcile menu option (delegated to AnkiExportManager)."""
        self._ensure_anki_manager().reconcile_menu_option()

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
                "Some definitions are abbreviated. View any by number; Enter to continue.",
                accent="dim",
            )
            while True:
                try:
                    choice = read_line("Show full definitions for # (Enter/Esc to finish): ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                # Check for ESC sequence
                if "\x1b" in choice:
                    break
                if not choice or choice == "0":
                    break
                if choice.isdigit():
                    entry_number = int(choice)
                    full_text = truncated_definitions.get(entry_number)
                    if full_text is None:
                        self.ui.warning("Please enter a valid entry number.")
                        continue
                    self.ui.panel(
                        full_text,
                        title=f"Definitions for entry {entry_number}",
                        border_style="dark_orange",
                        expand=True,
                    )
                    continue
                self.ui.warning("Enter a number or press Enter to finish.")

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
