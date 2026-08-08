"""Read-only downloads for authoritative data and automatic backup snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import threading
from typing import Any
from urllib.parse import quote


_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class MobileStorage:
    """Expose recovery copies without allowing browser-side mutation or restore."""

    def __init__(self, builder: Any, *, state_lock: threading.RLock):
        self.builder = builder
        self._state_lock = state_lock
        self.root = builder.latex_file.parent.resolve()

    def describe(self) -> dict[str, Any]:
        with self._state_lock:
            current = [self._describe(path, "current") for path in self._source_paths()]
            backups = [self._describe(path, "backup") for path in self._backup_paths()]
        return {
            "current": [item for item in current if item is not None],
            "backups": [item for item in backups if item is not None],
        }

    def resolve_download(self, filename: str) -> Path:
        if not _SAFE_NAME.fullmatch(filename):
            raise ValueError("Invalid data download name.")
        candidate = (self.root / filename).resolve()
        if not candidate.is_relative_to(self.root) or not candidate.is_file():
            raise FileNotFoundError(filename)
        allowed = {path.resolve() for path in (*self._source_paths(), *self._backup_paths())}
        if candidate not in allowed:
            raise FileNotFoundError(filename)
        return candidate

    def _source_paths(self) -> tuple[Path, ...]:
        candidates = [
            self.builder.latex_file,
            self.builder.eng_to_target_latex_file,
            self.builder.target_to_eng_latex_file,
            self.builder.exported_words_file,
        ]
        return tuple(
            path
            for value in candidates
            if value is not None
            for path in (Path(value),)
            if path.parent.resolve() == self.root
        )

    def _backup_paths(self) -> tuple[Path, ...]:
        prefixes = tuple(f"{path.name}." for path in self._source_paths())
        try:
            candidates = (
                path
                for path in self.root.iterdir()
                if path.is_file()
                and path.name.endswith(".bak")
                and path.name.startswith(prefixes)
            )
            return tuple(
                sorted(candidates, key=lambda path: path.stat().st_mtime_ns, reverse=True)[:40]
            )
        except OSError:
            return ()

    @staticmethod
    def _describe(path: Path, kind: str) -> dict[str, Any] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return {
            "filename": path.name,
            "kind": kind,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(
                stat.st_mtime,
                tz=timezone.utc,
            ).isoformat(),
            "download_url": f"/api/storage/download/{quote(path.name)}",
        }


__all__ = ["MobileStorage"]
