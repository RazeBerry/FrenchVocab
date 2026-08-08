from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Callable, Collection, Dict, Iterable, List, MutableMapping, Optional, Sequence, Tuple

from .file_safety import file_lock


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
    from vocab_builder.compat import config_home
    return config_home(create=True) / "history"


ErrorHandler = Optional[Callable[[str], None]]


@dataclass
class TranslationLogger:
    """Append-only JSONL translator/vocab history."""

    language_code: str
    base_dir: Path
    enabled: bool = True
    file_pattern: str = "{language}_translations.jsonl"
    fallback_base_dirs: Sequence[Path] = ()
    on_error: ErrorHandler = None

    def __post_init__(self) -> None:
        if not isinstance(self.base_dir, Path):
            self.base_dir = Path(self.base_dir)
        self.fallback_base_dirs = tuple(Path(path) for path in self.fallback_base_dirs)

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
    # Read helpers
    # --------------------------------------------------------------------- #
    def read_recent_vocab_entries(
        self,
        limit: Optional[int] = 15,
        *,
        actions: Optional[Collection[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return the most recent vocab entries from the JSONL history.

        Reads the history file, filters for ``flow == "vocab"`` records,
        optionally filters by action, and returns the last *limit* entries in
        reverse-chronological order. Pass ``limit=None`` to read the full vocab
        history. Returns an empty list if the file is missing or unreadable.
        """
        if limit is not None and limit <= 0:
            return []

        paths = [path for path in self._record_paths_for_read() if path.exists()]
        if not paths:
            return []

        allowed_actions = {str(action) for action in actions} if actions else None
        try:
            vocab_records: List[Dict[str, Any]] = []
            for path in paths:
                with file_lock(path):
                    with path.open("r", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if record.get("flow") != "vocab":
                                continue
                            if (
                                allowed_actions is not None
                                and record.get("action", "new") not in allowed_actions
                            ):
                                continue
                            vocab_records.append(record)
            vocab_records.sort(key=lambda record: str(record.get("timestamp", "")))
            if limit is not None:
                vocab_records = vocab_records[-limit:]
            return list(reversed(vocab_records))
        except OSError:
            return []

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    def _record_path(self) -> Path:
        return self.base_dir / self.file_pattern.format(language=self.language_code)

    def _record_paths_for_read(self) -> Tuple[Path, ...]:
        paths = [self._record_path()]
        for base_dir in self.fallback_base_dirs:
            paths.append(Path(base_dir) / self.file_pattern.format(language=self.language_code))
        deduped: List[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)
        return tuple(deduped)

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
            _append_jsonl_record(path, record)
        except Exception as exc:  # pragma: no cover - defensive path
            if self.on_error:
                self.on_error(f"Failed to write translation history: {exc}")


@dataclass
class CompositionLogger:
    """Append-only JSONL composition-practice history."""

    language_code: str
    base_dir: Path
    enabled: bool = True
    file_pattern: str = "{language}_compositions.jsonl"
    fallback_base_dirs: Sequence[Path] = ()
    on_error: ErrorHandler = None

    def __post_init__(self) -> None:
        if not isinstance(self.base_dir, Path):
            self.base_dir = Path(self.base_dir)
        self.fallback_base_dirs = tuple(Path(path) for path in self.fallback_base_dirs)

    def record_path(self) -> Path:
        return self.base_dir / self.file_pattern.format(language=self.language_code)

    def record_paths_for_read(self) -> Tuple[Path, ...]:
        paths = [self.record_path()]
        for base_dir in self.fallback_base_dirs:
            paths.append(Path(base_dir) / self.file_pattern.format(language=self.language_code))
        deduped: List[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)
        return tuple(deduped)

    def log_attempt(self, record: MutableMapping[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            path = _ensure_path(self.record_path())
            _append_jsonl_record(path, dict(record))
        except Exception as exc:  # pragma: no cover - defensive path
            if self.on_error:
                self.on_error(f"Failed to write composition history: {exc}")


def _append_jsonl_record(path: Path, record: Dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
