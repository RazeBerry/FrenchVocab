"""Unit tests for core/file_safety.py atomic write utilities."""

import os
import random
import tempfile
import threading
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from unittest.mock import patch

from vocab_builder.core.file_safety import (
    AtomicFileWriter,
    atomic_copy_file,
    atomic_write_text,
    file_lock,
)


class TestAtomicFileWriter(unittest.TestCase):
    """Tests for the AtomicFileWriter context manager."""

    _BACKUP_RETENTION_ENV_NAMES = (
        "VOCABBUILDER_MAX_BACKUPS",
        "FRENCHVOCAB_MAX_BACKUPS",
        "FRENCH_VOCAB_MAX_BACKUPS",
    )

    def _clear_backup_retention_env(self) -> None:
        for env_name in self._BACKUP_RETENTION_ENV_NAMES:
            os.environ.pop(env_name, None)

    def _write_version_series(self, path: Path, write_count: int) -> list[str]:
        versions = [f"version-{i}" for i in range(write_count + 1)]
        path.write_text(versions[0])

        class IncrementingDatetime:
            calls = 0

            @classmethod
            def now(cls, tz):
                cls.calls += 1
                return real_datetime(2026, 6, 12, 12, 0, 0, cls.calls, tzinfo=tz)

        with patch("vocab_builder.core.file_safety.datetime", IncrementingDatetime):
            for index in range(1, write_count + 1):
                atomic_write_text(path, versions[index], create_backup=True)
                self.assertEqual(path.read_text(), versions[index])

        return versions

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

    def test_atomic_write_prunes_timestamped_snapshots_to_default_cap(self):
        """Test that default retention keeps the ten newest timestamped snapshots."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"

            with patch.dict(os.environ, {}, clear=False):
                self._clear_backup_retention_env()
                versions = self._write_version_series(path, 12)

            snapshots = sorted(Path(td).glob("test.txt.*.bak"))
            self.assertEqual(len(snapshots), 10)
            self.assertEqual(
                [snapshot.read_text() for snapshot in snapshots],
                versions[2:12],
            )

    def test_backup_retention_preserves_latest_backup_and_non_matching_neighbors(self):
        """Test that only strict timestamped snapshots are pruning candidates."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            neighbor = Path(td) / "test.txt.not-a-timestamp.bak"
            recovered = Path(td) / "test.txt.20260612T120000000000Z.recovered_bak"
            suffix_neighbor = Path(td) / "test.txt.20260612T120000000000Z.bak.extra"
            neighbor.write_text("neighbor")
            recovered.write_text("recovered")
            suffix_neighbor.write_text("suffix neighbor")

            with patch.dict(os.environ, {"VOCABBUILDER_MAX_BACKUPS": "3"}, clear=False):
                versions = self._write_version_series(path, 5)

            snapshots = sorted(Path(td).glob("test.txt.20260612T*.bak"))
            self.assertEqual(len(snapshots), 3)
            self.assertEqual(path.with_suffix(".txt.bak").read_text(), versions[-2])
            self.assertEqual(neighbor.read_text(), "neighbor")
            self.assertEqual(recovered.read_text(), "recovered")
            self.assertEqual(suffix_neighbor.read_text(), "suffix neighbor")

    def test_backup_retention_preserves_other_source_snapshots(self):
        """Test that snapshots for a different source file are never pruned."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            other_snapshot = Path(td) / "other.txt.20260612T120000000000Z.bak"
            other_snapshot.write_text("other source")

            with patch.dict(os.environ, {"VOCABBUILDER_MAX_BACKUPS": "3"}, clear=False):
                self._write_version_series(path, 5)

            self.assertEqual(other_snapshot.read_text(), "other source")
            self.assertEqual(len(sorted(Path(td).glob("test.txt.*.bak"))), 3)

    def test_backup_retention_honors_max_backups_env(self):
        """Test that VOCABBUILDER_MAX_BACKUPS overrides the default cap."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"

            with patch.dict(os.environ, {"VOCABBUILDER_MAX_BACKUPS": "3"}, clear=False):
                versions = self._write_version_series(path, 5)

            snapshots = sorted(Path(td).glob("test.txt.*.bak"))
            self.assertEqual(len(snapshots), 3)
            self.assertEqual(
                [snapshot.read_text() for snapshot in snapshots],
                versions[2:5],
            )

    def test_backup_retention_zero_disables_pruning(self):
        """Test that VOCABBUILDER_MAX_BACKUPS=0 keeps unlimited snapshots."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"

            with patch.dict(os.environ, {"VOCABBUILDER_MAX_BACKUPS": "0"}, clear=False):
                versions = self._write_version_series(path, 12)

            snapshots = sorted(Path(td).glob("test.txt.*.bak"))
            self.assertEqual(len(snapshots), 12)
            self.assertEqual(
                [snapshot.read_text() for snapshot in snapshots],
                versions[:-1],
            )

    def test_backup_retention_garbage_env_falls_back_to_default(self):
        """Test that invalid VOCABBUILDER_MAX_BACKUPS values fall back to ten."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"

            with patch.dict(os.environ, {"VOCABBUILDER_MAX_BACKUPS": "garbage"}, clear=False):
                versions = self._write_version_series(path, 12)

            snapshots = sorted(Path(td).glob("test.txt.*.bak"))
            self.assertEqual(len(snapshots), 10)
            self.assertEqual(
                [snapshot.read_text() for snapshot in snapshots],
                versions[2:12],
            )

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

            created_backup = atomic_write_text(path, "new content", create_backup=True)

            self.assertTrue(path.exists())
            backup = path.with_suffix(".txt.bak")
            self.assertFalse(backup.exists())
            self.assertIsNone(created_backup)

    def test_atomic_write_new_file_does_not_report_stale_backup(self):
        """Test that stale backups are not reported as created for new files."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "new_file.txt"
            stale_backup = path.with_suffix(".txt.bak")
            stale_backup.write_text("stale backup")

            backup = atomic_write_text(path, "new content", create_backup=True)

            self.assertEqual(path.read_text(), "new content")
            self.assertEqual(stale_backup.read_text(), "stale backup")
            self.assertIsNone(backup)

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

            with patch.dict(os.environ, {"VOCABBUILDER_MAX_BACKUPS": "0"}, clear=False):
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
        """Test that atomic writes create parent directories."""
        with tempfile.TemporaryDirectory() as td:
            nested_dir = Path(td) / "a" / "b" / "c"
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
