from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
from typing import Any, Callable, Dict, Iterable, List, MutableMapping, Optional, Sequence, Tuple

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_examples(examples: Iterable[Tuple[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for fr, en in examples:
        normalized.append({"source": fr, "target": en})
    return normalized


def _ensure_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def default_history_base_dir() -> Path:
    """Default history location outside the repository working tree."""
    return Path(os.path.expanduser("~/.frenchvocab/history"))


ErrorHandler = Optional[Callable[[str], None]]
_PATH_LOCKS: Dict[Path, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


@dataclass
class TranslationLogger:
    """Append-only JSONL translator/vocab history."""

    language_code: str
    base_dir: Path
    enabled: bool = True
    file_pattern: str = "{language}_translations.jsonl"
    on_error: ErrorHandler = None

    def __post_init__(self) -> None:
        if not isinstance(self.base_dir, Path):
            self.base_dir = Path(self.base_dir)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def log_vocab_entry(
        self,
        *,
        word: str,
        word_type: str,
        definitions: Sequence[str],
        examples: Sequence[Tuple[str, str]],
        source_text: Optional[str],
        normalized_key: str,
        provider: Optional[str],
        latex_file: Path,
        action: str = "new",
        metadata: Optional[MutableMapping[str, Any]] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "action": action,
            "word": word,
            "word_type": word_type,
            "definitions": list(definitions),
            "examples": _normalize_examples(examples),
            "source_text": source_text,
            "normalized_key": normalized_key,
            "provider": provider,
            "file": str(latex_file),
        }
        if metadata:
            payload["metadata"] = dict(metadata)
        self._append_record("vocab", payload)

    def log_merge_entry(
        self,
        *,
        word: str,
        final_type: str,
        merged_definitions: Sequence[str],
        merged_examples: Sequence[Tuple[str, str]],
        provider: Optional[str],
        latex_file: Path,
        added_definitions: Sequence[str],
        added_examples: Sequence[Tuple[str, str]],
        normalized_key: str,
    ) -> None:
        payload: Dict[str, Any] = {
            "action": "merge",
            "word": word,
            "word_type": final_type,
            "definitions": list(merged_definitions),
            "examples": _normalize_examples(merged_examples),
            "provider": provider,
            "file": str(latex_file),
            "normalized_key": normalized_key,
            "metadata": {
                "added_definitions": list(added_definitions),
                "added_examples": _normalize_examples(added_examples),
            },
        }
        self._append_record("vocab", payload)

    def log_translator_entry(
        self,
        *,
        direction: str,
        source_text: str,
        target_text: str,
        normalized_key: str,
        provider: Optional[str],
        latex_file: Path,
        source_label: str,
        target_label: str,
    ) -> None:
        payload = {
            "direction": direction,
            "source_text": source_text,
            "target_text": target_text,
            "normalized_key": normalized_key,
            "provider": provider,
            "file": str(latex_file),
            "source_label": source_label,
            "target_label": target_label,
        }
        self._append_record("translator", payload)

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    def _record_path(self) -> Path:
        return self.base_dir / self.file_pattern.format(language=self.language_code)

    def _append_record(self, flow: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        record: Dict[str, Any] = {
            "timestamp": _timestamp(),
            "language": self.language_code,
            "flow": flow,
            **payload,
        }
        try:
            path = _ensure_path(self._record_path())
            line = json.dumps(record, ensure_ascii=False) + "\n"
            with _path_lock(path):
                with path.open("a", encoding="utf-8") as handle:
                    _lock_handle(handle)
                    try:
                        handle.write(line)
                        handle.flush()
                        os.fsync(handle.fileno())
                    finally:
                        _unlock_handle(handle)
        except Exception as exc:  # pragma: no cover - defensive path
            if self.on_error:
                self.on_error(f"Failed to write translation history: {exc}")


def _path_lock(path: Path) -> threading.Lock:
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(path)
        if lock is None:
            lock = threading.Lock()
            _PATH_LOCKS[path] = lock
        return lock


def _lock_handle(handle: Any) -> None:
    if fcntl is None:
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_handle(handle: Any) -> None:
    if fcntl is None:
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
