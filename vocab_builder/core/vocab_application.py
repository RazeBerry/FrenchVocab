"""Public capture boundary shared by terminal and headless interfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

from vocab_builder.languages import LanguageConfig
from vocab_builder.models import WordEntry

from .bulk_add import BulkAddReport, DuplicatePolicy
from .history_logger import TranslationLogger


class VocabCapturePort(Protocol):
    """Operations an alternate vocabulary-capture interface may depend on."""

    language_code: str
    language_config: LanguageConfig
    latex_file: Path
    max_word_length: int
    max_words: Optional[int]
    sentence_examples_in_vocab: bool
    history_logger: Optional[TranslationLogger]
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

    def record_acquisition_order(self, word: str) -> None: ...


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

    def record_acquisition_order(self, word: str) -> None:
        self._ensure_anki_manager().register_entry_order(word)
