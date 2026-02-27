"""
Atomic file operations and backup utilities for data safety.

Provides utilities to prevent data loss from:
- Interrupted writes (power loss, crashes)
- Concurrent access
- Disk full conditions
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional


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
        fd, temp_path = tempfile.mkstemp(
            dir=self.target_path.parent,
            prefix=f".{self.target_path.name}.",
            suffix=".tmp"
        )
        os.close(fd)
        self._temp_file = Path(temp_path)
        return self._temp_file

    def __exit__(self, exc_type, _exc_val, _exc_tb):
        if exc_type is not None:
            # Exception occurred - clean up temp file, don't modify original
            self._cleanup_temp()
            return False

        # Success path - create backup and atomic rename
        try:
            if self.create_backup and self.target_path.exists():
                self._backup_path = self.target_path.with_suffix(
                    self.target_path.suffix + self.backup_suffix
                )
                try:
                    os.link(self.target_path, self._backup_path)
                except OSError:
                    shutil.copy2(self.target_path, self._backup_path)

            # Atomic replace (os.replace is atomic on POSIX)
            os.replace(self._temp_file, self.target_path)
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
    with AtomicFileWriter(path, create_backup=create_backup) as temp_path:
        temp_path.write_text(content, encoding=encoding)

    if create_backup and path.with_suffix(path.suffix + ".bak").exists():
        return path.with_suffix(path.suffix + ".bak")
    return None

