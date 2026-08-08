"""Headless application service used by the private mobile interface.

The service deliberately reuses the existing VocabBuilder controller and
VocabRepository.  It only replaces the interactive terminal questions with a
two-step preview/save API suitable for a phone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import secrets
import threading
from typing import Any, Callable, Optional

from vocab_builder.core.file_safety import file_lock
from vocab_builder.core.text_utils import sanitize_user_text
from vocab_builder.core.vocab_application import VocabCapturePort
from vocab_builder.models import WordEntry


class MobileServiceError(RuntimeError):
    """Base class for errors safe to expose through the mobile API."""

    status_code = 500
    code = "mobile_service_error"

    def __init__(self, message: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidInputError(MobileServiceError):
    status_code = 422
    code = "invalid_input"


class DuplicateEntryError(MobileServiceError):
    status_code = 409
    code = "duplicate_entry"


class AIUnavailableError(MobileServiceError):
    status_code = 503
    code = "ai_unavailable"


class PreviewNotFoundError(MobileServiceError):
    status_code = 404
    code = "preview_not_found"


class SaveFailedError(MobileServiceError):
    status_code = 500
    code = "save_failed"


class PrivateAccessError(MobileServiceError):
    status_code = 403
    code = "private_access_denied"


@dataclass(frozen=True)
class MobilePreview:
    """AI result awaiting explicit confirmation from the user."""

    token: str
    language: str
    original_input: str
    word: str
    input_type: str
    word_type: str
    definitions: list[str]
    examples: list[tuple[str, str]]
    spelling_suggestion: Optional[str]
    created_at: datetime

    def as_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["examples"] = [
            {"source": source, "target": target}
            for source, target in self.examples
        ]
        return payload


class MobileVocabService:
    """Thread-safe, non-interactive facade around the existing vocab workflow."""

    def __init__(
        self,
        builder: VocabCapturePort,
        *,
        preview_ttl: timedelta = timedelta(minutes=20),
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ):
        self.builder = builder
        self.preview_ttl = preview_ttl
        self._token_factory = token_factory
        self._previews: dict[str, MobilePreview] = {}
        self._saved_receipts: dict[str, tuple[datetime, dict[str, Any]]] = {}
        # Provider clients and the repository are stateful. A single lock keeps
        # one user's phone and laptop requests deterministic.
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        with self._lock:
            entries = self.builder.word_entries
            return {
                "language": self.builder.language_code,
                "language_name": self.builder.language_config.display_name,
                "provider": self.builder.provider_label,
                "ai_available": bool(self.builder.api_available),
                "entry_count": len(entries),
                "data_file": self.builder.latex_file.name,
            }

    def preview(self, raw_text: str) -> MobilePreview:
        with self._lock:
            self._prune_previews()
            original = self._validate_input(raw_text)
            self._raise_if_duplicate(original)

            if not self.builder.api_available:
                reason = self.builder.api_error_reason or "The AI provider is not configured."
                raise AIUnavailableError(reason)

            response = self.builder.query_ai(original)
            if not response:
                reason = self.builder.api_error_reason or "The AI provider returned no result."
                raise AIUnavailableError(reason)

            word_type, definitions, examples = self.builder.parse_ai_response(response)
            if not definitions:
                raise AIUnavailableError(
                    "The AI response did not contain a usable definition. Please try again."
                )

            input_type = self.builder.detect_input_type(original)
            suggestion = self._spelling_suggestion(original, response, input_type)
            final_word = suggestion or original
            self._raise_if_duplicate(final_word)

            word_type = next(
                (value.strip() for value in word_type if value.strip()),
                "Unknown",
            ) if isinstance(word_type, list) else str(word_type or "Unknown")
            examples = list(examples)
            if word_type.lower() == "sentence" and not self.builder.sentence_examples_in_vocab:
                examples = []

            preview = MobilePreview(
                token=self._token_factory(),
                language=self.builder.language_code,
                original_input=original,
                word=final_word,
                input_type=input_type,
                word_type=word_type,
                definitions=list(definitions),
                examples=examples,
                spelling_suggestion=suggestion,
                created_at=datetime.now(timezone.utc),
            )
            self._previews[preview.token] = preview
            return preview

    def save(self, token: str, *, use_original: bool = False) -> dict[str, Any]:
        with self._lock:
            self._prune_previews()
            saved_receipt = self._saved_receipts.get(token)
            if saved_receipt is not None:
                return dict(saved_receipt[1])

            preview = self._previews.get(token)
            if preview is None:
                raise PreviewNotFoundError(
                    "That preview expired or was already saved. Generate it again."
                )

            with file_lock(self.builder.latex_file):
                word = preview.original_input if use_original else preview.word
                self._raise_if_duplicate(word)
                report = self.builder.add_vocab_entries(
                    [
                        WordEntry(
                            word=word,
                            type=preview.word_type,
                            definitions=list(preview.definitions),
                            examples=list(preview.examples),
                        )
                    ],
                    on_duplicate="error",
                )
                if not report.ok:
                    self._raise_if_duplicate(word)
                    detail = report.outcomes[0].detail if report.outcomes else ""
                    raise SaveFailedError(detail or "The vocabulary file could not be updated.")
                if report.count("added") != 1:
                    raise SaveFailedError("The vocabulary entry was not saved.")

                self._log_history(preview, saved_word=word)
                receipt = {
                    "word": word,
                    "entry_count": len(self.builder.word_entries),
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }
                self._saved_receipts[token] = (datetime.now(timezone.utc), receipt)
                del self._previews[token]
                return dict(receipt)

    def recent(self, limit: int = 8) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 30))
        logger = self.builder.history_logger
        if not logger or not logger.enabled:
            return []
        records = logger.read_recent_vocab_entries(limit=safe_limit)
        return [self._history_record_for_json(record) for record in records]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        needle = sanitize_user_text(query).casefold()
        if not needle:
            return []
        safe_limit = max(1, min(limit, 50))
        with self._lock:
            matches: list[dict[str, Any]] = []
            for entry in self.builder.word_entries.values():
                word = str(entry.get("word", ""))
                definitions = list(entry.get("definitions_list", []))
                searchable = " ".join([word, *definitions]).casefold()
                if needle not in searchable:
                    continue
                matches.append(
                    {
                        "word": word,
                        "word_type": str(entry.get("type", "")),
                        "definitions": definitions,
                        "examples": [
                            {"source": source, "target": target}
                            for source, target in entry.get("examples_list", [])
                        ],
                    }
                )
            matches.sort(key=lambda item: item["word"].casefold())
            return matches[:safe_limit]

    def _validate_input(self, raw_text: str) -> str:
        text = sanitize_user_text(raw_text or "")
        if not text:
            raise InvalidInputError("Type a word or phrase first.")
        if self.builder.max_words is not None and len(text.split()) > self.builder.max_words:
            raise InvalidInputError(
                f"Please limit the entry to {self.builder.max_words} words."
            )
        if len(text) > self.builder.max_word_length:
            raise InvalidInputError(
                f"Please limit the entry to {self.builder.max_word_length} characters."
            )
        if not self.builder.is_valid_input(text):
            raise InvalidInputError(
                f"That text contains characters unsupported for "
                f"{self.builder.language_config.display_name}."
            )
        return text

    def _raise_if_duplicate(self, word: str) -> None:
        existing_key = self.builder.check_duplicate(word)
        if not existing_key:
            return
        existing = self.builder.word_entries.get(existing_key, {})
        existing_word = str(existing.get("word") or existing_key)
        raise DuplicateEntryError(
            f"{existing_word} is already in your vocabulary.",
            details={"existing_word": existing_word},
        )

    def _spelling_suggestion(
        self,
        original: str,
        response: str,
        input_type: str,
    ) -> Optional[str]:
        if input_type == "sentence":
            return None
        suggestion = self.builder.suggest_spelling(original, response)
        return suggestion if suggestion and suggestion != original else None

    def _log_history(self, preview: MobilePreview, *, saved_word: str) -> None:
        logger = self.builder.history_logger
        if not logger or not logger.enabled:
            return
        metadata: dict[str, Any] = {"surface": "mobile"}
        if saved_word != preview.original_input:
            metadata.update(
                {
                    "original_input": preview.original_input,
                    "saved_word": saved_word,
                    "corrected_word": preview.word,
                }
            )
        logger.log_vocab_entry(
            action="new",
            word=saved_word,
            word_type=preview.word_type,
            definitions=preview.definitions,
            examples=preview.examples,
            source_text=preview.original_input,
            normalized_key=self.builder.normalize_word(saved_word),
            provider=self.builder.provider_label,
            latex_file=self.builder.latex_file,
            metadata=metadata,
        )

    def _prune_previews(self) -> None:
        cutoff = datetime.now(timezone.utc) - self.preview_ttl
        expired = [
            token
            for token, preview in self._previews.items()
            if preview.created_at < cutoff
        ]
        for token in expired:
            del self._previews[token]
        expired_receipts = [
            token
            for token, (saved_at, _receipt) in self._saved_receipts.items()
            if saved_at < cutoff
        ]
        for token in expired_receipts:
            del self._saved_receipts[token]

    @staticmethod
    def _history_record_for_json(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "word": record.get("word", ""),
            "word_type": record.get("word_type", ""),
            "definitions": list(record.get("definitions", [])),
            "examples": list(record.get("examples", [])),
            "timestamp": record.get("timestamp", ""),
            "action": record.get("action", "new"),
        }
