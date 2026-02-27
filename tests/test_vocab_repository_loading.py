from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.vocab_repository import VocabRepository
from languages import get_language_config


def _repo(tmp_path: Path) -> VocabRepository:
    latex_file = tmp_path / "FrenchVocab.tex"
    latex_file.write_text("", encoding="utf-8")
    return VocabRepository(
        latex_file=latex_file,
        entry_command="\\entry",
        language_config=get_language_config("fr"),
        ui=MagicMock(),
    )


def test_ensure_entries_loaded_retries_after_transient_failure(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    calls = {"count": 0}

    def _flaky_load_entries():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient parse error")
        return [
            SimpleNamespace(
                word="bonjour",
                type="noun",
                definitions=["hello"],
                examples=[("bonjour", "hello")],
            )
        ]

    repo.repo.load_entries = _flaky_load_entries  # type: ignore[assignment]

    with pytest.raises(RuntimeError):
        repo.ensure_entries_loaded()

    assert repo._entries_loaded is False
    assert repo._entries_loading is False
    assert calls["count"] == 1

    repo.ensure_entries_loaded()

    assert calls["count"] == 2
    assert repo._entries_loaded is True
    assert "bonjour" in repo.word_entries
