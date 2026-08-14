"""The cross-process lock must not live in the temp directory.

A systemd unit with PrivateTmp=true gets a private /tmp namespace, so a
temp-directory lock stops excluding the CLI running outside the unit and
concurrent saves silently drop entries.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from vocab_builder.core.file_safety import _lock_path_for, file_lock


def test_lock_lives_beside_the_data_file(tmp_path):
    data = tmp_path / "FrenchVocab.tex"
    data.write_text("", encoding="utf-8")

    lock_path = _lock_path_for(data)

    assert lock_path.parent == data.resolve().parent
    assert lock_path.name == ".FrenchVocab.tex.lock"


def test_lock_ignores_the_process_temp_directory(tmp_path, monkeypatch):
    data_root = tmp_path / "authoritative"
    data_root.mkdir()
    data = data_root / "GermanVocab.tex"
    data.write_text("", encoding="utf-8")
    private_temp = tmp_path / "private-tmp"
    private_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private_temp))

    lock_path = _lock_path_for(data)

    assert lock_path.parent == data_root.resolve()
    assert private_temp.resolve() not in lock_path.parents


def test_same_file_resolves_to_one_lock_through_different_paths(tmp_path):
    nested = tmp_path / "collections"
    nested.mkdir()
    data = nested / "FrenchVocab.tex"
    data.write_text("", encoding="utf-8")

    indirect = nested / ".." / "collections" / "FrenchVocab.tex"

    assert _lock_path_for(data) == _lock_path_for(indirect)


def test_lock_falls_back_to_temp_when_the_directory_is_read_only(tmp_path):
    read_only = tmp_path / "locked"
    read_only.mkdir()
    data = read_only / "FrenchVocab.tex"
    data.write_text("", encoding="utf-8")
    read_only.chmod(0o500)
    try:
        lock_path = _lock_path_for(data)
        assert Path(tempfile.gettempdir()) in lock_path.parents
    finally:
        read_only.chmod(0o700)


def test_file_lock_is_reentrant_within_one_process(tmp_path):
    data = tmp_path / "FrenchVocab.tex"
    data.write_text("", encoding="utf-8")

    with file_lock(data):
        with file_lock(data):
            data.write_text("nested", encoding="utf-8")

    assert data.read_text(encoding="utf-8") == "nested"
