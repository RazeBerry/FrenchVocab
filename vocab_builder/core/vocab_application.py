"""Public capture boundary shared by terminal and headless interfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

from vocab_builder.languages import LanguageConfig
from vocab_builder.models import WordEntry

from .bulk_add import BulkAddReport, DuplicatePolicy
from .history_logger import TranslationLogger
from .providers.manager import available_provider_ids


class VocabCapturePort(Protocol):
    """Operations an alternate vocabulary-capture interface may depend on."""

    language_code: str
    language_config: LanguageConfig
    latex_file: Path
    max_word_length: int
    max_words: Optional[int]
    route_sentences: bool
    sentence_examples_in_vocab: bool
    history_logger: Optional[TranslationLogger]
    target_to_eng_translator: Any
    api_available: bool
    api_error_reason: Optional[str]
    word_entries: dict[str, dict[str, Any]]

    @property
    def provider_label(self) -> str: ...

    def is_valid_input(self, word: str) -> bool: ...

    def detect_input_type(self, text: str) -> str: ...

    def query_ai(self, word: str) -> str: ...

    def try_restore_ai(self) -> bool: ...

    def parse_ai_response(
        self,
        response: str,
    ) -> tuple[Any, list[str], list[tuple[str, str]]]: ...

    def suggest_spelling(self, word: str, ai_response: str) -> Optional[str]: ...

    def check_duplicate(self, word: str) -> Optional[str]: ...

    def normalize_word(self, word: str) -> str: ...

    def add_vocab_entries(
        self,
        entries: Sequence[WordEntry],
        *,
        on_duplicate: DuplicatePolicy = "skip",
        dry_run: bool = False,
    ) -> BulkAddReport: ...

    def record_acquisition_order(self, word: str) -> bool: ...

    def get_composition_coach(self) -> Any: ...

    def get_anki_manager(self) -> Any: ...

    def provider_settings(self) -> dict[str, Any]: ...

    def configure_provider_noninteractive(
        self,
        provider: str,
        api_key: Optional[str] = None,
    ) -> tuple[bool, str]: ...

    def test_provider_connection(self) -> tuple[bool, str]: ...


class VocabCaptureMixin:
    """VocabBuilder implementation of the capture port's added operations."""

    @property
    def provider_label(self) -> str:
        return self._provider_label()

    def suggest_spelling(self, word: str, ai_response: str) -> Optional[str]:
        return self._spelling_checker.suggest(word, ai_response)

    def try_restore_ai(self) -> bool:
        return self._llm.try_silent_reinit()

    def add_vocab_entries(
        self,
        entries: Sequence[WordEntry],
        *,
        on_duplicate: DuplicatePolicy = "skip",
        dry_run: bool = False,
    ) -> BulkAddReport:
        return self._vocab_repo.bulk_add_entries(
            entries,
            on_duplicate=on_duplicate,
            dry_run=dry_run,
        )

    def record_acquisition_order(self, word: str) -> bool:
        return self._ensure_anki_manager().register_entry_order(word)

    def get_composition_coach(self) -> Any:
        return self._ensure_composition_coach()

    def get_anki_manager(self) -> Any:
        return self._ensure_anki_manager()

    def provider_settings(self) -> dict[str, Any]:
        configured = []
        for provider in available_provider_ids():
            metadata = self.provider_manager.get_metadata(provider)
            resolution = self.provider_manager.resolve_provider_silently(metadata)
            configured.append(
                {
                    "id": provider,
                    "name": metadata.display_name,
                    "configured": resolution is not None,
                    "documentation_url": metadata.doc_url,
                }
            )
        return {
            "active": self.provider,
            "label": self.provider_label,
            "available": self.api_available,
            "error": self.api_error_reason,
            "providers": configured,
        }

    def configure_provider_noninteractive(
        self,
        provider: str,
        api_key: Optional[str] = None,
    ) -> tuple[bool, str]:
        metadata = self.provider_manager.get_metadata(provider)
        if api_key is None:
            resolution = self.provider_manager.resolve_provider_silently(metadata)
            if resolution is None:
                return False, f"No stored {metadata.display_name} credential was found."
        else:
            resolution, feedback = self.provider_manager.configure_noninteractive(
                metadata,
                api_key,
            )
            if resolution is None:
                return False, feedback.message
        if not self._llm.apply_resolution_noninteractive(resolution):
            return False, self.api_error_reason or "The provider could not be initialized."
        return True, f"{metadata.display_name} is connected."

    def test_provider_connection(self) -> tuple[bool, str]:
        return self._llm.test_connection()
