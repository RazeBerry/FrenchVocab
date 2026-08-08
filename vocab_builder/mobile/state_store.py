"""Durable restart state for the single-worker mobile request service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vocab_builder.core.file_safety import atomic_copy_file, atomic_write_text, file_lock


_STATE_VERSION = 1


class MobileStateStore:
    """Persist short-lived tokens and repairable transactions atomically.

    Vocabulary remains authoritative in LaTeX.  This file only keeps request
    continuity across browser reloads and service restarts and records coupled
    history/Anki work that must be retried after a partial process failure.
    """

    def __init__(self, data_root: Path, language: str):
        self.path = Path(data_root) / f".mobile-{language}-state.json"

    def read(self) -> dict[str, Any]:
        with file_lock(self.path):
            if not self.path.exists():
                return self.empty()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                self._preserve_corrupt_state()
                return self.empty()
            if not isinstance(payload, dict) or payload.get("version") != _STATE_VERSION:
                self._preserve_corrupt_state()
                return self.empty()
            return {
                "version": _STATE_VERSION,
                "previews": _dict_or_empty(payload.get("previews")),
                "receipts": _dict_or_empty(payload.get("receipts")),
                "transactions": _dict_or_empty(payload.get("transactions")),
                "practice": _dict_or_empty(payload.get("practice")),
                "translations": _dict_or_empty(payload.get("translations")),
            }

    def write(self, payload: dict[str, Any]) -> None:
        normalized = {
            "version": _STATE_VERSION,
            "previews": _dict_or_empty(payload.get("previews")),
            "receipts": _dict_or_empty(payload.get("receipts")),
            "transactions": _dict_or_empty(payload.get("transactions")),
            "practice": _dict_or_empty(payload.get("practice")),
            "translations": _dict_or_empty(payload.get("translations")),
        }
        content = json.dumps(
            normalized,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        with file_lock(self.path):
            atomic_write_text(self.path, content + "\n", create_backup=False)

    @staticmethod
    def empty() -> dict[str, Any]:
        return {
            "version": _STATE_VERSION,
            "previews": {},
            "receipts": {},
            "transactions": {},
            "practice": {},
            "translations": {},
        }

    def _preserve_corrupt_state(self) -> None:
        if not self.path.exists():
            return
        corrupt = self.path.with_suffix(self.path.suffix + ".corrupt")
        try:
            atomic_copy_file(self.path, corrupt)
        except OSError:
            pass


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


__all__ = ["MobileStateStore"]
