"""Headless application service used by the private mobile interface.

The service deliberately reuses the existing VocabBuilder controller and
VocabRepository.  It only replaces the interactive terminal questions with a
two-step preview/save API suitable for a phone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import secrets
import threading
from typing import Any, Callable, Optional

from vocab_builder.core.file_safety import file_lock
from vocab_builder.core.text_utils import sanitize_user_text
from vocab_builder.core.vocab_application import VocabCapturePort
from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.models import WordEntry

from .state_store import MobileStateStore
from .library import MobileLibrary, entry_for_json
from .translations import MobileTranslations
from .practice import MobilePractice
from .anki import MobileAnki
from .settings import MobileSettings
from .storage import MobileStorage


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
    duplicate_action: str = "new"
    existing_word: Optional[str] = None
    route_recommended: bool = False
    existing_entry: Optional[dict[str, Any]] = None
    new_definitions: list[str] = field(default_factory=list)
    new_examples: list[tuple[str, str]] = field(default_factory=list)
    variant_word: Optional[str] = None

    def as_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["examples"] = [
            {"source": source, "target": target}
            for source, target in self.examples
        ]
        payload["new_examples"] = [
            {"source": source, "target": target}
            for source, target in self.new_examples
        ]
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "MobilePreview":
        examples = [
            (str(item.get("source", "")), str(item.get("target", "")))
            for item in payload.get("examples", [])
            if isinstance(item, dict)
        ]
        new_examples = [
            (str(item.get("source", "")), str(item.get("target", "")))
            for item in payload.get("new_examples", [])
            if isinstance(item, dict)
        ]
        return cls(
            token=str(payload["token"]),
            language=str(payload["language"]),
            original_input=str(payload["original_input"]),
            word=str(payload["word"]),
            input_type=str(payload.get("input_type", "word")),
            word_type=str(payload.get("word_type", "Unknown")),
            definitions=[str(value) for value in payload.get("definitions", [])],
            examples=examples,
            spelling_suggestion=(
                str(payload["spelling_suggestion"])
                if payload.get("spelling_suggestion")
                else None
            ),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            duplicate_action=str(payload.get("duplicate_action", "new")),
            existing_word=(
                str(payload["existing_word"])
                if payload.get("existing_word")
                else None
            ),
            route_recommended=bool(payload.get("route_recommended", False)),
            existing_entry=(
                dict(payload["existing_entry"])
                if isinstance(payload.get("existing_entry"), dict)
                else None
            ),
            new_definitions=[
                str(value) for value in payload.get("new_definitions", [])
            ],
            new_examples=new_examples,
            variant_word=(
                str(payload["variant_word"])
                if payload.get("variant_word")
                else None
            ),
        )


class MobileVocabService:
    """Thread-safe, non-interactive facade around the existing vocab workflow."""

    def __init__(
        self,
        builder: VocabCapturePort,
        *,
        preview_ttl: timedelta = timedelta(minutes=20),
        workflow_ttl: timedelta = timedelta(days=1),
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ):
        self.builder = builder
        self.preview_ttl = preview_ttl
        self.workflow_ttl = workflow_ttl
        self._token_factory = token_factory
        self._previews: dict[str, MobilePreview] = {}
        self._saved_receipts: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._transactions: dict[str, dict[str, Any]] = {}
        self._practice_attempts: dict[str, dict[str, Any]] = {}
        self._translation_previews: dict[str, dict[str, Any]] = {}
        self._state_store = MobileStateStore(
            self.builder.latex_file.parent,
            self.builder.language_code,
        )
        # Protect preview/receipt state and repository access. Provider calls
        # deliberately release this lock so status and search remain responsive.
        self._lock = threading.RLock()
        self._ai_lock = threading.Lock()
        self.library = MobileLibrary(builder, state_lock=self._lock)
        self._restore_state()
        self.translations = MobileTranslations(
            builder,
            previews=self._translation_previews,
            token_factory=self._token_factory,
            persist=self._persist_state,
            ai_lock=self._ai_lock,
            state_lock=self._lock,
        )
        self.practice = MobilePractice(
            builder,
            attempts=self._practice_attempts,
            token_factory=self._token_factory,
            persist=self._persist_state,
            ai_lock=self._ai_lock,
            state_lock=self._lock,
        )
        self.anki = MobileAnki(
            builder,
            token_factory=self._token_factory,
            state_lock=self._lock,
        )
        self.settings = MobileSettings(builder, ai_lock=self._ai_lock)
        self.storage = MobileStorage(builder, state_lock=self._lock)
        self._repair_transactions()

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._repair_transactions()
            entries = self.builder.word_entries
            return {
                "language": self.builder.language_code,
                "language_name": self.builder.language_config.display_name,
                "provider": self.builder.provider_label,
                "ai_available": bool(self.builder.api_available),
                "supports_translation": bool(
                    self.builder.language_config.supports_translation
                ),
                "supports_practice": bool(self.builder.enable_composition),
                "entry_count": len(entries),
                "data_file": self.builder.latex_file.name,
                "sync_pending": len(self._transactions),
            }

    def preview(
        self,
        raw_text: str,
        *,
        duplicate_action: str = "reject",
    ) -> MobilePreview:
        if duplicate_action not in {"reject", "merge", "variant"}:
            raise InvalidInputError("Choose merge or variant for an existing entry.")
        with self._lock:
            self._prune_previews()
            original = self._validate_input(raw_text)
            existing_word = self._existing_word(original)
            if existing_word and duplicate_action == "reject":
                self._raise_if_duplicate(original)
            ai_ready = bool(self.builder.api_available)

        # Provider recovery and generation are slow and do not touch repository
        # state, so same-language status and search requests remain available.
        with self._ai_lock:
            if not ai_ready and not self.builder.try_restore_ai():
                raise AIUnavailableError(
                    self.builder.api_error_reason
                    or "The AI provider is not configured."
                )

            response = self.builder.query_ai(original)

        with self._lock:
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
            corrected_existing = self._existing_word(final_word)
            if corrected_existing and duplicate_action == "reject":
                # Generation has already completed. Return its merge diff rather
                # than discard paid-for work and require the same call again.
                duplicate_action = "merge"
            existing_word = corrected_existing or existing_word

            word_type = next(
                (value.strip() for value in word_type if value.strip()),
                "Unknown",
            ) if isinstance(word_type, list) else str(word_type or "Unknown")
            examples = list(examples)
            if word_type.lower() == "sentence" and not self.builder.sentence_examples_in_vocab:
                examples = []

            existing_entry = None
            new_definitions: list[str] = []
            new_examples: list[tuple[str, str]] = []
            variant_word = None
            if existing_word:
                existing_entry, new_definitions, new_examples = self._merge_diff(
                    existing_word,
                    list(definitions),
                    examples,
                )
                if duplicate_action == "variant":
                    variant_word = self._unique_variant(final_word)

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
                duplicate_action=(duplicate_action if existing_word else "new"),
                existing_word=existing_word,
                route_recommended=bool(
                    input_type == "sentence"
                    and word_type.casefold() == "sentence"
                    and self.builder.route_sentences
                    and self.builder.language_config.supports_translation
                    and self.builder.target_to_eng_translator is not None
                ),
                existing_entry=existing_entry,
                new_definitions=new_definitions,
                new_examples=new_examples,
                variant_word=variant_word,
            )
            self._previews[preview.token] = preview
            self._persist_state()
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
                action = preview.duplicate_action
                added_definitions = len(preview.definitions)
                added_examples = len(preview.examples)
                if action == "variant":
                    word = self._unique_variant(word)
                elif action == "merge" and preview.existing_word:
                    existing_entry, new_definitions, new_examples = self._merge_diff(
                        preview.existing_word,
                        preview.definitions,
                        preview.examples,
                    )
                    if existing_entry is None:
                        raise SaveFailedError(
                            "The existing entry selected for merge no longer exists."
                        )
                    word = str(existing_entry["word"])
                    added_definitions = len(new_definitions)
                    added_examples = len(new_examples)
                    if added_definitions == 0 and added_examples == 0:
                        receipt = {
                            "word": word,
                            "action": "unchanged",
                            "entry_count": len(self.builder.word_entries),
                            "saved_at": datetime.now(timezone.utc).isoformat(),
                            "sync_pending": False,
                            "added_definitions": 0,
                            "added_examples": 0,
                        }
                        self._saved_receipts[token] = (
                            datetime.now(timezone.utc),
                            receipt,
                        )
                        del self._previews[token]
                        self._persist_state()
                        return dict(receipt)

                transaction = {
                    "operation_id": token,
                    "preview": preview.as_json(),
                    "word": word,
                    "action": action,
                    "primary_committed": False,
                    "history_done": False,
                    "anki_done": action == "merge",
                    "added_definitions": added_definitions,
                    "added_examples": added_examples,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                self._transactions[token] = transaction
                # A journal entry must reach disk before the authoritative file
                # changes.  A process failure can then replay every remaining
                # coupled step without guessing whether the request existed.
                self._persist_state()

                try:
                    self._commit_transaction_primary(transaction)
                except DuplicateEntryError:
                    # A competing session won before this operation changed
                    # the file. Do not leave a journal that recovery could
                    # later mistake for our own committed write.
                    self._transactions.pop(token, None)
                    self._persist_state()
                    raise
                receipt = {
                    "word": word,
                    "action": "merged" if action == "merge" else "added",
                    "entry_count": len(self.builder.word_entries),
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "sync_pending": True,
                    "added_definitions": int(transaction["added_definitions"]),
                    "added_examples": int(transaction["added_examples"]),
                }
                transaction["receipt"] = receipt
                transaction["primary_committed"] = True
                self._persist_state()

                self._complete_transaction_auxiliary(transaction)
                receipt["sync_pending"] = not self._transaction_complete(transaction)
                self._saved_receipts[token] = (datetime.now(timezone.utc), receipt)
                del self._previews[token]
                if self._transaction_complete(transaction):
                    del self._transactions[token]
                self._persist_state()
                return dict(receipt)

    def _commit_transaction_primary(self, transaction: dict[str, Any]) -> None:
        preview = MobilePreview.from_json(transaction["preview"])
        word = str(transaction["word"])
        action = str(transaction["action"])
        entry = WordEntry(
            word=word,
            type=preview.word_type,
            definitions=list(preview.definitions),
            examples=list(preview.examples),
        )

        if action == "merge":
            if not preview.existing_word:
                raise SaveFailedError("The existing entry selected for merge no longer exists.")
            # Use the corrected/existing spelling so the repository's atomic
            # merge planner resolves the intended normalized entry.
            entry = WordEntry(
                word=preview.existing_word,
                type=entry.type,
                definitions=entry.definitions,
                examples=entry.examples,
            )
            report = self.builder.add_vocab_entries([entry], on_duplicate="merge")
            expected = "merged"
        else:
            self._raise_if_duplicate(word)
            report = self.builder.add_vocab_entries([entry], on_duplicate="error")
            expected = "added"

        if not report.ok or report.count(expected) != 1:
            if action != "merge":
                self._raise_if_duplicate(word)
            detail = report.outcomes[0].detail if report.outcomes else ""
            raise SaveFailedError(detail or "The vocabulary file could not be updated.")

    def _complete_transaction_auxiliary(self, transaction: dict[str, Any]) -> None:
        preview = MobilePreview.from_json(transaction["preview"])
        word = str(transaction["word"])
        operation_id = str(transaction["operation_id"])

        if not transaction.get("history_done"):
            transaction["history_done"] = self._log_history(
                preview,
                saved_word=word,
                operation_id=operation_id,
                action=("merge" if transaction.get("action") == "merge" else "new"),
            )
        if not transaction.get("anki_done"):
            try:
                transaction["anki_done"] = bool(
                    self.builder.record_acquisition_order(word)
                )
            except Exception as exc:
                transaction["anki_done"] = False
                ui = getattr(self.builder, "ui", None)
                if ui is not None:
                    ui.warning(
                        "The vocabulary entry was saved, but its Anki acquisition "
                        f"order is queued for repair: {exc}"
                    )

    @staticmethod
    def _transaction_complete(transaction: dict[str, Any]) -> bool:
        return bool(transaction.get("history_done") and transaction.get("anki_done"))

    def recent(self, limit: int = 8) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 30))
        logger = self.builder.history_logger
        if not logger or not logger.enabled:
            return []
        records = logger.read_recent_vocab_entries(limit=safe_limit)
        with self._lock:
            return [
                self._reconcile_with_stored_entry(self._history_record_for_json(record))
                for record in records
            ]

    def _reconcile_with_stored_entry(self, row: dict[str, Any]) -> dict[str, Any]:
        """Let history supply the order and the vocabulary file supply the content.

        A history record keeps the word exactly as it was typed, while the
        vocabulary file capitalizes on write, so the same entry would otherwise
        appear in two different cases depending on which endpoint produced the
        row. Reading the stored entry also keeps definitions and examples from
        going stale after a later merge. Records whose entry has since been
        removed fall back to the history copy.
        """
        existing_key = self.builder.check_duplicate(str(row.get("word", "")))
        if not existing_key:
            return row
        entry = self.builder.word_entries.get(existing_key)
        if not entry:
            return row
        row["word"] = str(entry.get("word") or row.get("word", ""))
        row["word_type"] = str(entry.get("type") or row.get("word_type", ""))
        row["definitions"] = list(entry.get("definitions_list", [])) or row.get("definitions", [])
        stored_examples = [
            {"source": source, "target": target}
            for source, target in entry.get("examples_list", [])
        ]
        if stored_examples:
            row["examples"] = stored_examples
        return row

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            if not sanitize_user_text(query):
                return []
            return self.library.page(
                query=query,
                page_size=max(1, min(limit, 50)),
            )["items"]

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
            details={
                "existing_word": existing_word,
                "existing_entry": self._entry_for_json(existing),
                "actions": ["merge", "variant", "skip"],
            },
        )

    def _existing_word(self, word: str) -> Optional[str]:
        existing_key = self.builder.check_duplicate(word)
        if not existing_key:
            return None
        existing = self.builder.word_entries.get(existing_key, {})
        return str(existing.get("word") or existing_key)

    def _merge_diff(
        self,
        existing_word: str,
        definitions: list[str],
        examples: list[tuple[str, str]],
    ) -> tuple[
        Optional[dict[str, Any]],
        list[str],
        list[tuple[str, str]],
    ]:
        """Compare candidates with the current repository merge semantics."""
        existing_key = self.builder.check_duplicate(existing_word)
        if not existing_key:
            return None, [], []
        existing = self.builder.word_entries.get(existing_key)
        if not existing:
            return None, [], []
        existing_entry = entry_for_json(existing)
        existing_examples = [
            (str(item.get("source", "")), str(item.get("target", "")))
            for item in existing_entry["examples"]
        ]
        return (
            existing_entry,
            VocabRepository.new_definitions_for_merge(
                existing_entry["definitions"],
                definitions,
            ),
            VocabRepository.new_examples_for_merge(existing_examples, examples),
        )

    def _unique_variant(self, base_word: str) -> str:
        candidate = f"{base_word} - alt"
        if not self.builder.check_duplicate(candidate):
            return candidate
        for suffix in "abcdefghijklmnopqrstuvwxyz":
            candidate = f"{base_word} - alt {suffix}"
            if not self.builder.check_duplicate(candidate):
                return candidate
        index = 2
        while True:
            candidate = f"{base_word} - alt x{index}"
            if not self.builder.check_duplicate(candidate):
                return candidate
            index += 1

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

    def _log_history(
        self,
        preview: MobilePreview,
        *,
        saved_word: str,
        operation_id: str,
        action: str,
    ) -> bool:
        logger = self.builder.history_logger
        if not logger or not logger.enabled:
            return True
        if logger.has_operation(operation_id, flow="vocab"):
            return True
        metadata: dict[str, Any] = {
            "surface": "mobile",
            "operation_id": operation_id,
        }
        if saved_word != preview.original_input:
            metadata.update(
                {
                    "original_input": preview.original_input,
                    "saved_word": saved_word,
                    "corrected_word": preview.word,
                }
            )
        return logger.log_vocab_entry(
            action=action,
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

    def _restore_state(self) -> None:
        payload = self._state_store.read()
        for token, raw_preview in payload["previews"].items():
            try:
                self._previews[token] = MobilePreview.from_json(raw_preview)
            except (KeyError, TypeError, ValueError):
                continue
        for token, stored in payload["receipts"].items():
            if not isinstance(stored, dict):
                continue
            try:
                saved_at = datetime.fromisoformat(str(stored["saved_at"]))
                receipt = dict(stored["receipt"])
            except (KeyError, TypeError, ValueError):
                continue
            self._saved_receipts[token] = (saved_at, receipt)
        self._transactions = {
            str(token): dict(value)
            for token, value in payload["transactions"].items()
            if isinstance(value, dict)
        }
        self._practice_attempts = {
            str(token): dict(value)
            for token, value in payload["practice"].items()
            if isinstance(value, dict)
        }
        self._translation_previews = {
            str(token): dict(value)
            for token, value in payload["translations"].items()
            if isinstance(value, dict)
        }
        self._prune_previews()
        self._prune_auxiliary_state()

    def _persist_state(self) -> None:
        with self._lock:
            self._prune_auxiliary_state()
            self._state_store.write(
                {
                    "previews": {
                        token: preview.as_json()
                        for token, preview in self._previews.items()
                    },
                    "receipts": {
                        token: {
                            "saved_at": saved_at.isoformat(),
                            "receipt": receipt,
                        }
                        for token, (saved_at, receipt) in self._saved_receipts.items()
                    },
                    "transactions": self._transactions,
                    "practice": self._practice_attempts,
                    "translations": self._translation_previews,
                }
            )

    def _prune_auxiliary_state(self) -> None:
        cutoff = datetime.now(timezone.utc) - self.workflow_ttl

        def expired(payload: dict[str, Any]) -> bool:
            try:
                return datetime.fromisoformat(str(payload["created_at"])) < cutoff
            except (KeyError, TypeError, ValueError):
                return True

        for token, payload in list(self._translation_previews.items()):
            receipt = payload.get("saved_receipt")
            pending = bool(
                isinstance(receipt, dict) and receipt.get("history_pending")
            )
            if expired(payload) and not pending:
                self._translation_previews.pop(token, None)
        for token, payload in list(self._practice_attempts.items()):
            feedback = payload.get("feedback")
            pending = bool(
                isinstance(feedback, dict) and feedback.get("history_pending")
            )
            if expired(payload) and not pending:
                self._practice_attempts.pop(token, None)

    def _repair_transactions(self) -> None:
        changed = False
        for token, transaction in list(self._transactions.items()):
            try:
                if not transaction.get("primary_committed"):
                    word = str(transaction["word"])
                    if transaction.get("action") == "merge":
                        if not self._stored_entry_contains(transaction):
                            self._commit_transaction_primary(transaction)
                    elif not self.builder.check_duplicate(word):
                        self._commit_transaction_primary(transaction)
                    elif not self._stored_entry_matches(transaction):
                        # Another writer committed different content for this
                        # normalized word. This journal never owned the primary
                        # mutation, so it must not fabricate history or Anki
                        # acquisition state for it.
                        self._transactions.pop(token, None)
                        changed = True
                        continue
                    transaction["primary_committed"] = True

                if not isinstance(transaction.get("receipt"), dict):
                    preview = MobilePreview.from_json(transaction["preview"])
                    transaction["receipt"] = {
                        "word": str(transaction["word"]),
                        "action": (
                            "merged"
                            if transaction.get("action") == "merge"
                            else "added"
                        ),
                        "entry_count": len(self.builder.word_entries),
                        "saved_at": datetime.now(timezone.utc).isoformat(),
                        "sync_pending": True,
                        "added_definitions": int(
                            transaction.get("added_definitions", len(preview.definitions))
                        ),
                        "added_examples": int(
                            transaction.get("added_examples", len(preview.examples))
                        ),
                    }
                self._complete_transaction_auxiliary(transaction)
                receipt = transaction.get("receipt")
                if isinstance(receipt, dict):
                    receipt["sync_pending"] = not self._transaction_complete(transaction)
                    saved_at = datetime.fromisoformat(
                        str(receipt.get("saved_at") or datetime.now(timezone.utc).isoformat())
                    )
                    self._saved_receipts[token] = (saved_at, receipt)
                    self._previews.pop(token, None)
                if self._transaction_complete(transaction):
                    self._transactions.pop(token, None)
                changed = True
            except Exception:
                # The journal remains durable and a later request can retry.
                continue
        if changed:
            self._persist_state()

    def _stored_entry_matches(self, transaction: dict[str, Any]) -> bool:
        stored, preview = self._stored_entry_and_preview(transaction)
        if stored is None or preview is None:
            return False
        return (
            stored["word_type"].casefold() == preview.word_type.casefold()
            and stored["definitions"] == preview.definitions
            and stored["examples"]
            == [
                {"source": source, "target": target}
                for source, target in preview.examples
            ]
        )

    def _stored_entry_contains(self, transaction: dict[str, Any]) -> bool:
        stored, preview = self._stored_entry_and_preview(transaction)
        if stored is None or preview is None:
            return False
        expected_examples = [
            {"source": source, "target": target}
            for source, target in preview.examples
        ]
        return all(
            definition in stored["definitions"] for definition in preview.definitions
        ) and all(example in stored["examples"] for example in expected_examples)

    def _stored_entry_and_preview(
        self,
        transaction: dict[str, Any],
    ) -> tuple[Optional[dict[str, Any]], Optional[MobilePreview]]:
        preview = MobilePreview.from_json(transaction["preview"])
        existing_key = self.builder.check_duplicate(str(transaction["word"]))
        if not existing_key:
            return None, None
        existing = self.builder.word_entries.get(existing_key)
        if not existing:
            return None, None
        return entry_for_json(existing), preview

    @staticmethod
    def _entry_for_json(entry: dict[str, Any]) -> dict[str, Any]:
        return entry_for_json(entry)

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
