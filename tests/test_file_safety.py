"""Unit tests for core/file_safety.py atomic write utilities."""

import random
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from vocab_builder.core.file_safety import AtomicFileWriter, atomic_copy_file, atomic_write_text, file_lock


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

    def test_atomic_write_creates_timestamped_backup_snapshots(self):
        """Test that repeated writes keep more than the latest backup generation."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            path.write_text("original content")

            atomic_write_text(path, "first update", create_backup=True)
            atomic_write_text(path, "second update", create_backup=True)

            latest_backup = path.with_suffix(".txt.bak")
            self.assertEqual(latest_backup.read_text(), "first update")
            snapshots = sorted(Path(td).glob("test.txt.*.bak"))
            self.assertGreaterEqual(len(snapshots), 2)
            snapshot_contents = {snapshot.read_text() for snapshot in snapshots}
            self.assertIn("original content", snapshot_contents)
            self.assertIn("first update", snapshot_contents)

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

    def test_file_lock_serializes_read_modify_write_transactions(self):
        """Test that file_lock prevents lost updates across read-modify-write blocks."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "counter.txt"
            path.write_text("0")

            def increment():
                with file_lock(path):
                    current = int(path.read_text())
                    path.write_text(str(current + 1))

            threads = [threading.Thread(target=increment) for _ in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(path.read_text(), "20")

    def test_atomic_write_replace_failure_keeps_original(self):
        """Test that final replace failures do not expose partial content."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            path.write_text("original content")
            real_replace = __import__("os").replace

            def fail_final_replace(src, dst):
                if Path(dst) == path:
                    raise OSError("simulated replace failure")
                return real_replace(src, dst)

            with patch("vocab_builder.core.file_safety.os.replace", side_effect=fail_final_replace):
                with self.assertRaises(OSError):
                    atomic_write_text(path, "new content", create_backup=True)

            self.assertEqual(path.read_text(), "original content")
            self.assertEqual(path.with_suffix(".txt.bak").read_text(), "original content")
            temp_files = list(Path(td).glob(".*.tmp"))
            self.assertEqual(temp_files, [])

    def test_atomic_copy_file_failure_does_not_create_partial_destination(self):
        """Test that failed copies only leave temp files that are cleaned up."""
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.txt"
            destination = Path(td) / "destination.txt"
            source.write_text("safe backup content")

            def fail_copy(_source, temp_destination):
                Path(temp_destination).write_text("partial")
                raise OSError("simulated copy failure")

            with patch("vocab_builder.core.file_safety.shutil.copy2", side_effect=fail_copy):
                with self.assertRaises(OSError):
                    atomic_copy_file(source, destination)

            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(td).glob(".*.tmp")), [])

    def test_atomic_copy_file_failure_keeps_existing_destination(self):
        """Test that failed copies never clobber an existing destination."""
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.txt"
            destination = Path(td) / "destination.txt"
            source.write_text("new backup content")
            destination.write_text("current destination")

            def fail_copy(_source, temp_destination):
                Path(temp_destination).write_text("partial")
                raise OSError("simulated copy failure")

            with patch("vocab_builder.core.file_safety.shutil.copy2", side_effect=fail_copy):
                with self.assertRaises(OSError):
                    atomic_copy_file(source, destination)

            self.assertEqual(destination.read_text(), "current destination")
            self.assertEqual(list(Path(td).glob(".*.tmp")), [])

    def test_atomic_write_fuzz_preserves_previous_generations(self):
        """Fuzz repeated overwrites and verify every prior version remains recoverable."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fuzz.txt"
            rng = random.Random(20260430)
            versions = ["initial"]
            path.write_text(versions[0])

            for i in range(30):
                alphabet = "abcXYZ012{}[] \n"
                content = f"{i}:" + "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
                versions.append(content)
                atomic_write_text(path, content, create_backup=True)
                self.assertEqual(path.read_text(), content)

            self.assertEqual(path.with_suffix(".txt.bak").read_text(), versions[-2])
            snapshot_contents = {
                snapshot.read_text()
                for snapshot in Path(td).glob("fuzz.txt.*.bak")
            }
            self.assertTrue(set(versions[:-1]).issubset(snapshot_contents))


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
