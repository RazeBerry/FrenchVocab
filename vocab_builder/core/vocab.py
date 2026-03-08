import os
import shutil
import string
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from pathlib import Path
from rich.console import Console
from vocab_builder.anki_exporter import latex_to_anki_format as latex_to_anki_html
from vocab_builder.ai_response_parser import parse_ai_response_text
import time
import threading
from vocab_builder.languages import LanguageConfig, TranslatorConfig, default_language_code, get_language_config
from typing import TYPE_CHECKING

from .history_logger import TranslationLogger
from .vocab_repository import VocabRepository
from .llm_coordinator import LLMCoordinator
from .anki_manager import AnkiExportManager
from .spelling_checker import SpellingChecker
from .vocab_display_mixin import VocabDisplayMixin
from .vocab_merge_mixin import VocabMergeMixin
from .vocab_runtime_mixin import VocabRuntimeMixin
from .word_entry_workflow import (
    WordEntryWorkflow,
    WorkflowCallbacks,
    WorkflowOptions,
    WorkflowOutcome,
)
from .text_utils import detect_input_type as classify_input_type, sanitize_user_text, translator_title
from .menu_loop import main_menu_loop
from .session_ui import (
    build_welcome_message,
    resolve_welcome_provider_name,
    show_main_menu,
    show_post_translation_menu,
    show_translation_menu,
)
from vocab_builder.models import normalize_word_key
from vocab_builder.ui_helper import UIHelper, read_line
from vocab_builder.core.providers.manager import (
    ProviderManager,
    ProviderMetadata,
)

if TYPE_CHECKING:  # pragma: no cover - optional provider clients
    from vocab_builder.llm_client import GeminiClient  # noqa: F401
    from .translator import TranslatorCLI  # noqa: F401
    from .auto_translator import AutoTranslator  # noqa: F401


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
        try:
            return self._builder.word_entries
        except RuntimeError:
            return {}

    def ensure_entries_loaded(self) -> None:
        pass  # Test doubles set word_entries directly

    def normalize_word(self, word: str) -> str:
        # Keep adapter behavior aligned with production normalization.
        return normalize_word_key(word)

    def get_all_latex_entries(self) -> Set[str]:
        return set(self.word_entries.keys())


class FrenchVocabBuilder(VocabRuntimeMixin, VocabMergeMixin, VocabDisplayMixin):
    DEFAULT_LANGUAGE_CONFIG = get_language_config(None)
    DEFAULT_LANGUAGE_CODE = default_language_code()
    language_config: LanguageConfig = DEFAULT_LANGUAGE_CONFIG
    language_code: str = DEFAULT_LANGUAGE_CODE
    DEFINITION_PREVIEW_LIMIT = 60

    @property
    def word_entries(self) -> Dict[str, Any]:
        """Vocabulary entries keyed by lower-case token."""
        repo = getattr(self, "_vocab_repo", None)
        if repo is not None:
            repo.ensure_entries_loaded()
            return repo.word_entries
        fallback = getattr(self, "_word_entries_fallback", None)
        if fallback is not None:
            return fallback
        raise RuntimeError(
            "Cannot access word_entries: VocabRepository is not initialized. "
            "Construct FrenchVocabBuilder normally or set word_entries on test doubles."
        )

    @word_entries.setter
    def word_entries(self, value: Dict[str, Any]) -> None:
        repo = getattr(self, "_vocab_repo", None)
        if repo is not None:
            repo.word_entries = value
            repo.entry_count = len(value)
            return
        object.__setattr__(self, "_word_entries_fallback", value)

    @property
    def normalized_entries(self) -> Dict[str, str]:
        """Normalized lookup index mapping normalized text to canonical key."""
        repo = getattr(self, "_vocab_repo", None)
        if repo is not None:
            repo.ensure_entries_loaded()
            return repo.normalized_entries
        fallback = getattr(self, "_normalized_entries_fallback", None)
        if fallback is not None:
            return fallback
        raise RuntimeError(
            "Cannot access normalized_entries: VocabRepository is not initialized. "
            "Construct FrenchVocabBuilder normally or set normalized_entries on test doubles."
        )

    @normalized_entries.setter
    def normalized_entries(self, value: Dict[str, str]) -> None:
        repo = getattr(self, "_vocab_repo", None)
        if repo is not None:
            repo.normalized_entries = value
            return
        object.__setattr__(self, "_normalized_entries_fallback", value)

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
        provider: Optional[str] = None,
        verbose: bool = False,
        client: Optional["GeminiClient"] = None,
        language: Optional[str] = None,
        language_config: Optional[LanguageConfig] = None,
        eager_provider: bool = False,
    ):
        init_start = time.time()
        self._verbose_fallback = bool(verbose)
        self._configure_language(language=language, language_config=language_config)
        self._initialize_context()
        self._configure_file_paths(latex_file)
        self._initialize_vocab_repository()
        self._initialize_runtime_flags()
        self._spelling_checker = SpellingChecker(self.ui)

        load_config_start, load_config_end = self._initialize_llm(
            provider=provider,
            verbose=verbose,
            client=client,
            eager_provider=eager_provider,
        )
        self._initialize_anki_and_translators()
        self._complete_startup(
            init_start=init_start,
            load_config_start=load_config_start,
            load_config_end=load_config_end,
        )

    def _configure_language(
        self,
        *,
        language: Optional[str],
        language_config: Optional[LanguageConfig],
    ) -> None:
        if language and language_config:
            raise ValueError("Provide either language or language_config, not both.")

        resolved_config = language_config
        if resolved_config is None:
            resolved_language = language or self.DEFAULT_LANGUAGE_CODE
            resolved_config = get_language_config(resolved_language)

        self.language_config = resolved_config
        self.language_code = resolved_config.code
        self.vocab_template = resolved_config.vocab
        entry_command = self.vocab_template.entry_command or "\\entry"
        self.entry_command = entry_command if entry_command.startswith("\\") else f"\\{entry_command}"

    def _initialize_context(self) -> None:
        self.console = Console()
        self.ui = UIHelper(self.console)
        module_dir = Path(__file__).resolve().parent
        self.project_root = module_dir.parent
        self.provider_manager = ProviderManager(self.ui, self.project_root)

    def _configure_file_paths(self, latex_file: Optional[str]) -> None:
        self.default_vocab_filename = self.language_config.vocab_filename
        if latex_file is None:
            self.latex_file = self.project_root / self.default_vocab_filename
            base_dir = self.project_root
        else:
            self.latex_file = Path(latex_file)
            base_dir = self.latex_file.parent
        self.eng_to_fr_latex_file = base_dir / self.language_config.eng_to_target_filename
        self.fr_to_eng_latex_file = base_dir / self.language_config.target_to_eng_filename

    def _initialize_vocab_repository(self) -> None:
        if not self.latex_file.exists():
            temp_repo = VocabRepository(
                latex_file=self.latex_file,
                entry_command=self.entry_command,
                language_config=self.language_config,
                ui=self.ui,
                vocab_template=self.vocab_template,
            )
            temp_repo.create_initial_tex_file()

        self._vocab_repo = VocabRepository(
            latex_file=self.latex_file,
            entry_command=self.entry_command,
            language_config=self.language_config,
            ui=self.ui,
            vocab_template=self.vocab_template,
        )
        self.repo = self._vocab_repo.repo

    def _initialize_runtime_flags(self) -> None:
        self.max_word_length = 1000
        self.max_words: Optional[int] = None
        self.allow_sentence_punctuation: bool = True
        self.route_sentences: bool = True
        self.sentence_examples_in_vocab: bool = False
        self.config_file = "vocab_builder_config.json"
        self._config_data: Dict[str, Any] = {}
        self.history_logger: Optional[TranslationLogger] = None
        self._warmup_threads: List[threading.Thread] = []

        self._load_input_limits()
        self.history_logger = self._create_history_logger()

        self.eng_to_fr_translator: Optional["TranslatorCLI"] = None
        self.fr_to_eng_translator: Optional["TranslatorCLI"] = None
        self.auto_translator: Optional["AutoTranslator"] = None
        self.duplicate_resolution: Optional[Dict[str, str]] = None
        self.enable_auto_translator: bool = self._should_enable_auto_translator()

    def _initialize_llm(
        self,
        *,
        provider: Optional[str],
        verbose: bool,
        client: Optional["GeminiClient"],
        eager_provider: bool,
    ) -> tuple[float, float]:
        from vocab_builder.llm_client import ProviderFactory

        self.eager_provider = eager_provider or (provider is not None)
        requested_provider = provider or ProviderFactory.default_provider()
        provider_metadata: ProviderMetadata = self.provider_manager.get_metadata(requested_provider)

        load_config_start = time.time()
        self._llm = LLMCoordinator(
            ui=self.ui,
            provider_manager=self.provider_manager,
            provider_metadata=provider_metadata,
            verbose=verbose,
            client=client,
            eager=self.eager_provider,
        )
        self._llm.set_degraded_mode_callback(self._on_llm_degraded)
        self._llm.set_client_ready_callback(self._init_translators)
        load_config_end = time.time()
        return load_config_start, load_config_end

    def _initialize_anki_and_translators(self) -> None:
        exported_words_file = self._resolve_exported_words_path(self.project_root, self.latex_file.parent)
        self._anki = AnkiExportManager(
            ui=self.ui,
            language_config=self.language_config,
            vocab_repo=self._vocab_repo,
            exported_words_file=exported_words_file,
            project_root=self.project_root,
        )
        self._init_translators()

    def _complete_startup(
        self,
        *,
        init_start: float,
        load_config_start: float,
        load_config_end: float,
    ) -> None:
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("FRENCHVOCAB_FORCE_SYNC_LOAD"):
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
        self._llm.provider_metadata = self.provider_manager.get_metadata(value)

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
        llm = getattr(self, "_llm", None)
        if llm is not None:
            return llm.verbose
        return bool(getattr(self, "_verbose_fallback", False))

    @verbose.setter
    def verbose(self, value: bool):
        self._verbose_fallback = bool(value)
        llm = getattr(self, "_llm", None)
        if llm is not None:
            llm.verbose = bool(value)

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
            on_query_exception=self._handle_ai_exception,
        )
        self.fr_to_eng_translator = TranslatorCLI(
            console=self.console,
            client=self.client,
            config=target_to_eng,
            latex_file_path=self.fr_to_eng_latex_file,
            direction="target_to_eng",
            logger=self.history_logger,
            usage_callback=self._record_usage,
            on_query_exception=self._handle_ai_exception,
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
            on_query_exception=self._handle_ai_exception,
            verbose=self.verbose,
        )

    def _safe_warmup(self, fn, label: str) -> None:
        """Run a warm-up task defensively so background failures never block startup."""
        try:
            fn()
        except Exception as exc:  # pragma: no cover - best-effort telemetry
            if self.verbose:
                self.ui.debug(f"Warm-up task failed [{label}]: {exc}")

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
        return translator_title(config)

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

    def detect_input_type(self, text: str) -> str:
        """Classify input as word/expression/sentence."""
        return classify_input_type(text)

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

    def _provider_label(self) -> str:
        """Human-readable provider label (delegated to LLMCoordinator)."""
        return self._llm.provider_label

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
        except Exception as exc:
            self._history_log_error(f"Failed to write merge history: {exc}")

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
        return

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

    def display_existing_entry(self, word: str):
        self._ensure_entries_loaded()
        entry = self.word_entries.get(word.lower())
        if not entry:
            self.ui.warning(f"Entry for '{word}' not found.")
            return
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

    
    def _startup_alphabetize_best_effort(self) -> None:
        try:
            self.alphabetize_entries(silent=True)
        except (OSError, ValueError, RuntimeError) as exc:
            if self.verbose:
                self.ui.debug(f"Startup alphabetization skipped: {exc}")

    def _resolve_welcome_provider_name(self) -> str:
        return resolve_welcome_provider_name(self)

    def _build_welcome_message(self, provider_name: str) -> tuple[str, str]:
        return build_welcome_message(self, provider_name)

    def welcome_screen(self):
        self._startup_alphabetize_best_effort()
        provider_name = self._resolve_welcome_provider_name()
        message, panel_title = self._build_welcome_message(provider_name)
        self.ui.panel(message, title=panel_title, border_style="dark_orange")

    def show_menu(self):
        return show_main_menu(self)

    def show_translation_menu(self) -> str:
        """Display translation direction submenu."""
        return show_translation_menu(self)

    def show_anki_menu(self) -> str:
        """Display Anki submenu (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager().show_anki_menu()

    def handle_anki_tools(self) -> bool:
        """Route Anki workflows (delegated to AnkiExportManager)."""
        return self._ensure_anki_manager().handle_anki_tools()

    def _build_word_input_prompt(self) -> str:
        language_name = self.language_config.display_name
        limit_descriptors: list[str] = []
        if getattr(self, "max_words", None):
            limit_descriptors.append(f"≤{self.max_words} words")
        if getattr(self, "max_word_length", None):
            limit_descriptors.append(f"≤{self.max_word_length} chars")
        limit_hint = f" [{' • '.join(limit_descriptors)}]" if limit_descriptors else ""
        return f"\nEnter {language_name} text{limit_hint} (Esc to cancel): "

    def _read_word_input_line(self, prompt: str) -> str:
        try:
            line = read_line(prompt)
        except (EOFError, KeyboardInterrupt):
            self.ui.warning("Input cancelled. Returning to main menu.")
            return ""

        # Treat any ESC sequence as an immediate cancel
        if line and "\x1b" in line:
            self.ui.warning("Input cancelled via Esc. Returning to main menu.")
            return ""

        return line

    @staticmethod
    def _sanitize_word_input(text: str) -> str:
        return sanitize_user_text(text)

    def _validate_word_input(self, word: str) -> bool:
        if not word:
            self.ui.error("Cannot add vocabulary entry: input cannot be empty.")
            return False

        if self.max_words is not None and len(word.split()) > self.max_words:
            self.ui.error(f"Cannot add vocabulary entry: please limit to {self.max_words} words.")
            return False

        if len(word) > self.max_word_length:
            self.ui.error(
                f"Cannot add vocabulary entry: please limit to {self.max_word_length} characters."
            )
            return False

        if not self.is_valid_input(word):
            self.ui.error(
                "Cannot add vocabulary entry: input contains unsupported characters for "
                f"{self.language_config.display_name} text."
            )
            return False

        return True

    def get_word_input(self) -> str:
        """Read target-language text from the user.

        Instructions:
        - Type or paste your text, then press Enter to submit.
        - Press Esc to cancel.
        """
        prompt = self._build_word_input_prompt()
        line = self._read_word_input_line(prompt)
        if not line:
            return ""

        word = self._sanitize_word_input(line)
        if not self._validate_word_input(word):
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

    def insert_entry_alphabetically(self, new_entry: str, new_word: str) -> bool:
        """Insert a new LaTeX entry at the appropriate position."""
        return self._vocab_repo.insert_entry_alphabetically(new_entry, new_word)

    def alphabetize_entries(self, *, silent: bool = False) -> None:
        """Alphabetize the entries in the LaTeX file."""
        self._vocab_repo.alphabetize_entries(silent=silent)

    def exit_screen(self):
        # Best-effort alphabetization on clean exit
        try:
            self.alphabetize_entries(silent=True)
        except (OSError, ValueError, RuntimeError) as exc:
            if self.verbose:
                self.ui.debug(f"Exit alphabetization skipped: {exc}")

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

    def _provider_metadata_or_none(self) -> Optional[ProviderMetadata]:
        try:
            return self.provider_metadata
        except (AttributeError, RuntimeError):
            return None

    def _is_keyring_enabled(self) -> bool:
        manager = getattr(self, "provider_manager", None)
        return bool(getattr(manager, "_keyring_enabled", True))

    @staticmethod
    def _keyring_get_password_best_effort(service: str, username: str) -> Optional[str]:
        try:
            import keyring  # type: ignore[import]
        except ImportError:
            return None

        try:
            return keyring.get_password(service, username)
        except Exception:
            return None

    def _determine_key_source(self, metadata: Optional[ProviderMetadata]) -> str:
        if metadata is None:
            return "Unknown"

        env_value = os.environ.get(metadata.env_var)
        if not env_value:
            return "Unknown"

        if not self._is_keyring_enabled():
            return "Environment variable"

        stored_key = self._keyring_get_password_best_effort(
            "french_vocab_builder",
            metadata.keyring_name,
        )
        if stored_key and stored_key == env_value:
            return "System keychain"
        return "Environment variable"

    def _resolve_settings_connection_fields(self) -> tuple[str, str, str]:
        metadata = self._provider_metadata_or_none()
        provider_display = metadata.display_name if metadata else "Unknown"

        provider_name = "Not configured"
        connection_status = "[red]Disconnected[/red]"
        key_source = "Unknown"

        if self.api_available and self.client:
            connection_status = "[green]Connected[/green]"
            provider_name = provider_display
            key_source = self._determine_key_source(metadata)
        elif not self.api_available:
            connection_status = "[yellow]Unavailable[/yellow]"
            provider_name = f"{provider_display} (not connected)"
            key_source = "Not configured"

        return provider_name, connection_status, key_source

    def _build_settings_status_text(self) -> str:
        provider_name, connection_status, key_source = self._resolve_settings_connection_fields()

        status_text = (
            f"[bold]AI Provider:[/bold]      {provider_name}\n"
            f"[bold]Connection:[/bold]       {connection_status}\n"
            f"[bold]Key Source:[/bold]       {key_source}\n"
            f"[bold]Vocabulary File:[/bold]  {self.latex_file}\n"
            f"[bold]Total Entries:[/bold]    {self.entry_count} words\n"
        )

        if not self.api_available and self.api_error_reason:
            status_text += f"\n[yellow]Issue: {self.api_error_reason}[/yellow]"

        return status_text

    def _prompt_settings_action(self) -> Optional[str]:
        options = [
            ("test", "Test AI connection"),
            ("change_provider", "Change AI provider"),
            ("update_key", "Update API key"),
            ("view_files", "View file locations"),
            ("back", "Back to main menu"),
        ]

        try:
            return self.ui.interactive_menu(
                "Settings Actions",
                options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
                show_keys=False,
            )
        except KeyboardInterrupt:
            return None

    def _dispatch_settings_action(self, choice: Optional[str]) -> None:
        if not choice or choice == "back":
            return

        actions = {
            "test": self._test_ai_connection,
            "change_provider": self._change_provider_interactive,
            "update_key": self._update_api_key_interactive,
            "view_files": self._show_file_locations,
        }
        handler = actions.get(choice)
        if handler is not None:
            handler()

    def show_settings_screen(self):
        """Display current configuration and allow changes."""
        status_text = self._build_settings_status_text()
        self.ui.panel(status_text, title="Configuration Status", border_style="cyan")

        choice = self._prompt_settings_action()
        self._dispatch_settings_action(choice)

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

    def run(self):
        main_menu_loop(self)

    def handle_new_word_entry(self):
        """Handle the word entry flow by delegating to WordEntryWorkflow.

        This method creates a workflow instance and executes it, then handles
        the quick action menu for continued interaction. Uses an iterative loop
        instead of recursion to avoid stack overflow on repeated "add" actions.
        """
        while True:
            # Create workflow with current state
            workflow_options = WorkflowOptions(
                max_word_length=self.max_word_length,
                max_words=self.max_words,
                allow_sentence_punctuation=self.allow_sentence_punctuation,
                route_sentences=self.route_sentences,
                sentence_examples_in_vocab=self.sentence_examples_in_vocab,
                entry_command=self.entry_command,
            )
            workflow_callbacks = WorkflowCallbacks(
                provider_label_fn=self._provider_label,
                on_settings=self.show_settings_screen,
                on_post_translation_menu=self._show_post_translation_menu,
                get_word_input_fn=self.get_word_input,
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
            workflow = WordEntryWorkflow(
                vocab_repo=self._vocab_repo,
                llm=self._llm,
                ui=self.ui,
                language_config=self.language_config,
                history_logger=self.history_logger,
                spelling_checker=self._spelling_checker,
                fr_to_eng_translator=self.fr_to_eng_translator,
                options=workflow_options,
                callbacks=workflow_callbacks,
            )

            # Run the workflow
            outcome = workflow.run(self.ensure_llm_ready)

            # Sync duplicate_resolution state back
            self.duplicate_resolution = workflow.duplicate_resolution

            if outcome == WorkflowOutcome.ROUTED:
                if workflow.post_translation_action == "add":
                    continue
                return

            if outcome != WorkflowOutcome.SAVED:
                return

            # Quick action menu - iterative instead of recursive
            quick_action = self._show_word_entry_quick_actions()
            if quick_action == "add":
                continue  # Loop to add another word
            elif quick_action == "view":
                self.display_all_vocabulary()
            elif quick_action == "search":
                self.search_vocabulary()
            # "menu" or None (Esc) - return to main menu
            return

    def _show_word_entry_quick_actions(self) -> Optional[str]:
        """Show quick action menu after successful word entry.

        Returns the selected action key, or None on cancel.
        """
        try:
            return self.ui.interactive_menu(
                "What's next?",
                [
                    ("add", "Add another word"),
                    ("view", "View all vocabulary"),
                    ("search", "Search vocabulary"),
                    ("menu", "Return to main menu"),
                ],
                "Press Esc to return to main menu",
            )
        except KeyboardInterrupt:
            return None

    def _show_post_translation_menu(self) -> Optional[str]:
        return show_post_translation_menu(self)

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
