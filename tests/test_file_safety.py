"""Unit tests for core/file_safety.py atomic write utilities."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from vocab_builder.core.file_safety import AtomicFileWriter, atomic_write_text


class TestAtomicFileWriter(unittest.TestCase):
    """Tests for the AtomicFileWriter context manager."""

    def test_atomic_write_creates_backup(self):
        """Test that atomic write creates a backup of the original file."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            path.write_text("original content")

            atomic_write_text(path, "new content", create_backup=True)

            self.assertEqual(path.read_text(), "new content")
            backup = path.with_suffix(".txt.bak")
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(), "original content")

    def test_atomic_write_no_backup_when_disabled(self):
        """Test that backup is not created when create_backup=False."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            path.write_text("original content")

            atomic_write_text(path, "new content", create_backup=False)

            self.assertEqual(path.read_text(), "new content")
            backup = path.with_suffix(".txt.bak")
            self.assertFalse(backup.exists())

    def test_atomic_write_rollback_on_exception(self):
        """Test that original file is unchanged if exception occurs during write."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            path.write_text("original content")

            try:
                with AtomicFileWriter(path, create_backup=True) as temp_path:
                    temp_path.write_text("partial content")
                    raise ValueError("Simulated failure")
            except ValueError:
                pass

            # Original should be unchanged
            self.assertEqual(path.read_text(), "original content")

            # No temp files should remain (hidden files starting with .)
            temp_files = list(Path(td).glob(".*"))
            self.assertEqual(len(temp_files), 0, f"Temp files remaining: {temp_files}")

    def test_atomic_write_new_file(self):
        """Test creating a new file with atomic write."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "new_file.txt"

            # File doesn't exist yet
            self.assertFalse(path.exists())

            atomic_write_text(path, "new content", create_backup=False)

            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(), "new content")

    def test_atomic_write_new_file_no_backup(self):
        """Test that no backup is created for new files (nothing to backup)."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "new_file.txt"

            atomic_write_text(path, "new content", create_backup=True)

            self.assertTrue(path.exists())
            backup = path.with_suffix(".txt.bak")
            self.assertFalse(backup.exists())

    def test_atomic_write_preserves_encoding(self):
        """Test that UTF-8 encoding is preserved correctly."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "unicode.txt"

            content = "Héllo Wörld! 日本語 🎉"
            atomic_write_text(path, content, encoding="utf-8")

            self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_concurrent_writes_no_corruption(self):
        """Test that concurrent atomic writes don't corrupt data."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            path.write_text("initial")

            errors = []

            def writer(content: str):
                try:
                    atomic_write_text(path, content, create_backup=False)
                except Exception as e:
                    errors.append(str(e))

            threads = [
                threading.Thread(target=writer, args=(f"content-{i}",))
                for i in range(10)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # No errors should have occurred
            self.assertEqual(len(errors), 0, f"Errors: {errors}")

            # File should contain one valid content string (whichever finished last)
            final = path.read_text()
            self.assertTrue(
                final.startswith("content-"),
                f"File content corrupted: {final!r}"
            )


class TestAtomicWriterEdgeCases(unittest.TestCase):
    """Edge case tests for AtomicFileWriter."""

    def test_write_to_file_with_spaces_in_name(self):
        """Test atomic write to file with spaces in path."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "file with spaces.txt"

            atomic_write_text(path, "content")

            self.assertEqual(path.read_text(), "content")

    def test_write_to_deeply_nested_path(self):
        """Test that parent directories must already exist."""
        with tempfile.TemporaryDirectory() as td:
            # The atomic writer expects the parent directory to exist
            nested_dir = Path(td) / "a" / "b" / "c"
            nested_dir.mkdir(parents=True)
            path = nested_dir / "file.txt"

            atomic_write_text(path, "nested content")

            self.assertEqual(path.read_text(), "nested content")

    def test_empty_content(self):
        """Test writing empty content."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.txt"

            atomic_write_text(path, "")

            self.assertEqual(path.read_text(), "")

    def test_large_content(self):
        """Test writing large content."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "large.txt"

            # 1MB of content
            large_content = "x" * (1024 * 1024)
            atomic_write_text(path, large_content)

            self.assertEqual(path.read_text(), large_content)

    def test_atomic_write_fsyncs_file_and_directory(self):
        """Test that successful writes fsync both the temp file and parent directory."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "durable.txt"

            with patch("vocab_builder.core.file_safety.os.fsync") as mock_fsync:
                atomic_write_text(path, "content", create_backup=False)

            self.assertGreaterEqual(mock_fsync.call_count, 2)


if __name__ == "__main__":
    unittest.main()
