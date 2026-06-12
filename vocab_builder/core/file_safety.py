"""
Atomic file operations and backup utilities for data safety.

Provides utilities to prevent data loss from:
- Interrupted writes (power loss, crashes)
- Concurrent access
- Disk full conditions
"""

import hashlib
import os
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from vocab_builder.compat import get_env


_DEFAULT_MAX_BACKUP_SNAPSHOTS = 10
_MAX_BACKUPS_ENV_VAR = "VOCABBUILDER_MAX_BACKUPS"


class AtomicFileWriter:
    """
    Context manager for atomic file writes with optional backup.

    Usage:
        with AtomicFileWriter(path, create_backup=True) as temp_path:
            temp_path.write_text(content)
        # On success: backup created, atomic replace performed
        # On exception: temp cleaned up, original unchanged
    """

    def __init__(
        self,
        target_path: Path,
        create_backup: bool = True,
        backup_suffix: str = ".bak"
    ):
        self.target_path = Path(target_path)
        self.create_backup = create_backup
        self.backup_suffix = backup_suffix
        self._temp_file: Optional[Path] = None
        self._backup_path: Optional[Path] = None

    def __enter__(self) -> Path:
        # Create temp file in same directory (ensures same filesystem for atomic rename)
        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            dir=self.target_path.parent,
            prefix=f".{self.target_path.name}.",
            suffix=".tmp"
        )
        os.close(fd)
        self._temp_file = Path(temp_path)
        return self._temp_file

    @property
    def backup_path(self) -> Optional[Path]:
        """Latest backup path created by this writer, if any."""
        return self._backup_path

    def __exit__(self, exc_type, _exc_val, _exc_tb):
        if exc_type is not None:
            # Exception occurred - clean up temp file, don't modify original
            self._cleanup_temp()
            return False

        # Success path - create backup and atomic rename
        try:
            if self.create_backup and self.target_path.exists():
                self._backup_path = create_backup_snapshot(
                    self.target_path,
                    backup_suffix=self.backup_suffix,
                )

            _fsync_file(self._temp_file)
            # Atomic replace (os.replace is atomic on POSIX)
            os.replace(self._temp_file, self.target_path)
            _fsync_directory(self.target_path.parent)
        except Exception:
            # If backup/replace fails, clean up temp and re-raise
            self._cleanup_temp()
            raise

        return False

    def _cleanup_temp(self) -> None:
        """Remove temporary file if it exists."""
        if self._temp_file and self._temp_file.exists():
            try:
                self._temp_file.unlink()
            except OSError:
                pass  # Best effort cleanup


def atomic_write_text(
    path: Path,
    content: str,
    encoding: str = "utf-8",
    create_backup: bool = True
) -> Optional[Path]:
    """
    Atomically write text content to a file.

    Args:
        path: Target file path
        content: Text content to write
        encoding: File encoding (default: utf-8)
        create_backup: Whether to create a .bak backup (default: True)

    Returns:
        The backup path if one was created, None otherwise.

    Raises:
        OSError: If write fails (disk full, permissions, etc.)
    """
    path = Path(path)
    writer = AtomicFileWriter(path, create_backup=create_backup)
    with writer as temp_path:
        temp_path.write_text(content, encoding=encoding)

    return writer.backup_path


def atomic_copy_file(source: Path, destination: Path) -> None:
    """Atomically copy source to destination without exposing partial output."""
    _copy_file_atomic(Path(source), Path(destination))


_THREAD_LOCKS: dict[Path, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Cross-process lock for read-modify-write transactions on a data file."""
    lock_path = _lock_path_for(Path(path))
    thread_lock = _thread_lock_for(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with thread_lock:
        with lock_path.open("a", encoding="utf-8") as handle:
            _lock_handle(handle)
            try:
                yield
            finally:
                _unlock_handle(handle)


def create_backup_snapshot(path: Path, backup_suffix: str = ".bak") -> Optional[Path]:
    """Create a latest backup plus a timestamped snapshot for an existing file."""
    source = Path(path)
    if not source.exists() or not source.is_file():
        return None

    latest_backup = source.with_suffix(source.suffix + backup_suffix)
    _copy_file_atomic(source, latest_backup)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = source.with_name(f"{source.name}.{timestamp}{backup_suffix}")
    counter = 1
    while snapshot.exists():
        snapshot = source.with_name(f"{source.name}.{timestamp}.{counter}{backup_suffix}")
        counter += 1
    _copy_file_atomic(source, snapshot)
    _prune_backup_snapshots(source, backup_suffix)
    return latest_backup


def _max_backup_snapshots() -> int:
    raw_value = get_env(_MAX_BACKUPS_ENV_VAR)
    if raw_value is None:
        return _DEFAULT_MAX_BACKUP_SNAPSHOTS

    try:
        max_backups = int(raw_value)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_BACKUP_SNAPSHOTS

    if max_backups >= 1 or max_backups == 0:
        return max_backups
    return _DEFAULT_MAX_BACKUP_SNAPSHOTS


def _prune_backup_snapshots(source: Path, backup_suffix: str) -> None:
    max_backups = _max_backup_snapshots()
    if max_backups == 0:
        return

    snapshot_pattern = re.compile(
        rf"^{re.escape(source.name)}\.\d{{8}}T\d{{12}}Z(\.\d+)?{re.escape(backup_suffix)}$"
    )
    try:
        candidates = [
            candidate
            for candidate in source.parent.iterdir()
            if candidate.is_file() and snapshot_pattern.match(candidate.name)
        ]
    except OSError:
        return

    for stale_snapshot in sorted(candidates, key=lambda path: path.name)[:-max_backups]:
        try:
            stale_snapshot.unlink()
        except OSError:
            pass


def _lock_path_for(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / "vocabbuilder-file-locks" / f"{digest}.lock"


def _thread_lock_for(lock_path: Path) -> threading.RLock:
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(lock_path)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[lock_path] = lock
        return lock


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(source, temp_path)
        _fsync_file(temp_path)
        os.replace(temp_path, destination)
        _fsync_directory(destination.parent)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _lock_handle(handle) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_handle(handle) -> None:
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _fsync_file(path: Optional[Path]) -> None:
    if path is None or not path.exists():
        return

    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return

    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
