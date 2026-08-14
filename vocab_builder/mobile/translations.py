"""Headless translation use cases shared with the configured CLI translators."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any, Callable, Optional, Protocol

from vocab_builder.core.text_utils import sanitize_user_text
from vocab_builder.core.translator import TranslationDraft


class TranslationBuilder(Protocol):
    api_available: bool
    api_error_reason: Optional[str]
    eng_to_target_translator: Any
    target_to_eng_translator: Any
    auto_translator: Any

    def try_restore_ai(self) -> bool: ...


class MobileTranslations:
    """Expose directional and intelligent translation without console prompts."""

    def __init__(
        self,
        builder: TranslationBuilder,
        *,
        previews: dict[str, dict[str, Any]],
        token_factory: Callable[[], str],
        persist: Callable[[], None],
        ai_lock: threading.Lock,
        state_lock: threading.RLock,
    ):
        self.builder = builder
        self._previews = previews
        self._token_factory = token_factory
        self._persist = persist
        self._ai_lock = ai_lock
        self._state_lock = state_lock
        self._workflow_lock = threading.RLock()

    def describe(self) -> dict[str, Any]:
        with self._workflow_lock:
            self._repair_history()
            directions = []
            for key, translator in self._directional_translators():
                if translator is None:
                    continue
                directions.append(
                    {
                        "id": key,
                        "source_label": translator.source_label,
                        "target_label": translator.target_label,
                        "count": translator.entry_count,
                    }
                )
            return {
                "available": bool(directions),
                "auto_available": self.builder.auto_translator is not None,
                "directions": directions,
            }

    def preview(self, direction: str, source_text: str) -> dict[str, Any]:
        source = sanitize_user_text(source_text)
        if not source:
            raise ValueError("Type or paste text to translate first.")
        if len(source) > 10000:
            raise ValueError("Please limit translation input to 10,000 characters.")
        if not self.builder.api_available and not self.builder.try_restore_ai():
            raise RuntimeError(
                self.builder.api_error_reason or "The AI provider is unavailable."
            )

        with self._workflow_lock:
            with self._ai_lock:
                notes = None
                suspicious = False
                if direction == "auto":
                    automatic = self.builder.auto_translator
                    if automatic is None:
                        raise ValueError(
                            "Intelligent translation is unavailable for this language."
                        )
                    result = automatic.preview_translation(source)
                    if result is None:
                        raise RuntimeError(
                            "The AI could not determine a translation direction."
                        )
                    if automatic.direction_is_ambiguous(result.direction):
                        explanation = (result.notes or "").strip()
                        raise ValueError(
                            explanation
                            or "The source language is ambiguous. Choose a translation direction."
                        )
                    translator = automatic.translator_for_direction(result.direction)
                    if translator is None:
                        raise RuntimeError(
                            "The detected translation direction is unavailable."
                        )
                    resolved_direction = self._direction_for_translator(translator)
                    draft = translator.preview_translation(
                        source,
                        provided_translation=result.translation,
                    )
                    notes = result.notes
                    suspicious = automatic.translation_is_suspicious(
                        source,
                        result.translation,
                    )
                else:
                    resolved_direction = direction
                    translator = self._translator(direction)
                    draft = translator.preview_translation(source)

            if draft is None:
                raise RuntimeError("The AI provider returned no translation.")
            token = self._token_factory()
            payload = {
                "token": token,
                "direction": resolved_direction,
                "source_text": draft.source_text,
                "target_text": draft.target_text,
                "normalized_key": draft.normalized_key,
                "suspicious": suspicious or draft.suspicious,
                "dropped_fragment": draft.dropped_fragment,
                "existing_entry": draft.existing_entry,
                "notes": notes,
                "source_label": translator.source_label,
                "target_label": translator.target_label,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            with self._state_lock:
                self._previews[token] = payload
                self._persist()
            return dict(payload)

    def save(self, token: str) -> dict[str, Any]:
        # Holding the short-lived workflow lock makes retrying the same token
        # idempotent even when two phone requests arrive together. The
        # translator owns its own file lock for cross-process safety.
        with self._workflow_lock, self._state_lock:
            payload = self._previews.get(token)
            if payload is None:
                raise KeyError("That translation preview expired. Generate it again.")
            saved_receipt = payload.get("saved_receipt")
            if isinstance(saved_receipt, dict):
                if saved_receipt.get("history_pending"):
                    self._repair_payload_history(payload)
                    self._persist()
                return dict(saved_receipt)

            translator = self._translator(str(payload["direction"]))
            draft = TranslationDraft(
                source_text=str(payload["source_text"]),
                target_text=str(payload["target_text"]),
                normalized_key=str(payload["normalized_key"]),
                suspicious=bool(payload.get("suspicious")),
                dropped_fragment=(
                    str(payload["dropped_fragment"])
                    if payload.get("dropped_fragment")
                    else None
                ),
                existing_entry=(
                    dict(payload["existing_entry"])
                    if isinstance(payload.get("existing_entry"), dict)
                    else None
                ),
            )
            payload["save_started"] = True
            self._persist()
            result = translator.save_translation(draft, operation_id=token)
            if result.status == "failed":
                raise RuntimeError("The translation file could not be updated.")
            exact_result = result.target_text.strip() == draft.target_text.strip()
            history_pending = result.status == "saved" or (
                result.status == "duplicate" and exact_result
            )
            receipt = {
                "status": result.status,
                "direction": payload["direction"],
                "source_text": result.source_text,
                "target_text": result.target_text,
                "existing_entry": result.existing_entry,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                # A retry after a crash can observe the just-written pair as a
                # duplicate. Exact stored content proves the requested primary
                # outcome is present; a different competing translation must
                # never acquire history under this operation's identity.
                "history_pending": history_pending
                and not bool(payload.get("existing_entry")),
            }
            payload["saved_receipt"] = receipt
            self._repair_payload_history(payload)
            self._persist()
            return dict(receipt)

    def pairs(self, direction: str, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        with self._workflow_lock:
            translator = self._translator(direction)
            items = [
                {
                    "source": entry["source"],
                    "target": entry["target"],
                }
                for _, entry in sorted(translator.pairs.items())
            ]
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 200))
        start = (safe_page - 1) * safe_size
        return {
            "items": items[start : start + safe_size],
            "page": safe_page,
            "page_size": safe_size,
            "total": len(items),
            "has_more": start + safe_size < len(items),
        }

    def _translator(self, direction: str):
        mapping = dict(self._directional_translators())
        translator = mapping.get(direction)
        if translator is None:
            raise ValueError("That translation direction is unavailable.")
        return translator

    def _directional_translators(self):
        return (
            ("eng_to_target", self.builder.eng_to_target_translator),
            ("target_to_eng", self.builder.target_to_eng_translator),
        )

    def _direction_for_translator(self, expected: Any) -> str:
        for direction, translator in self._directional_translators():
            if translator is expected:
                return direction
        raise RuntimeError("The detected translator is not registered.")

    def _repair_history(self) -> None:
        changed = False
        with self._state_lock:
            for payload in self._previews.values():
                if self._repair_payload_history(payload):
                    changed = True
            if changed:
                self._persist()

    def _repair_payload_history(self, payload: dict[str, Any]) -> bool:
        receipt = payload.get("saved_receipt")
        if not isinstance(receipt, dict) or not receipt.get("history_pending"):
            return False
        translator = self._translator(str(payload["direction"]))
        draft = TranslationDraft(
            source_text=str(payload["source_text"]),
            target_text=str(payload["target_text"]),
            normalized_key=str(payload["normalized_key"]),
        )
        repair = getattr(translator, "repair_translation_history", None)
        if not callable(repair):
            receipt["history_pending"] = False
            return True
        if repair(draft, operation_id=str(payload["token"])):
            receipt["history_pending"] = False
            return True
        return False


__all__ = ["MobileTranslations"]
