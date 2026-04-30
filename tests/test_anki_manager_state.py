import json
from pathlib import Path
from unittest.mock import patch

import genanki

from vocab_builder.core.anki_manager import AnkiExportManager
from vocab_builder.languages import get_language_config


class _StubUI:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def warning(self, message, with_panel=False):  # noqa: ARG002
        self.warnings.append(message)

    def error(self, message, with_panel=False):  # noqa: ARG002
        self.errors.append(message)

    def info(self, *_args, **_kwargs):
        pass

    def panel(self, *_args, **_kwargs):
        pass


class _StubRepo:
    word_entries = {}

    def ensure_entries_loaded(self):
        return None


def _manager(path: Path, ui: _StubUI | None = None) -> AnkiExportManager:
    return AnkiExportManager(
        ui=ui or _StubUI(),
        language_config=get_language_config("fr"),
        vocab_repo=_StubRepo(),  # type: ignore[arg-type]
        exported_words_file=path,
        project_root=path.parent,
    )


def test_load_exported_words_recovers_from_invalid_words_field(tmp_path):
    path = tmp_path / "exported_words.json"
    path.write_text(json.dumps({"words": None, "deck_version": "v1"}), encoding="utf-8")
    ui = _StubUI()

    manager = _manager(path, ui)

    assert manager.exported_words == set()
    assert manager.exported_deck_version is None
    assert (tmp_path / "exported_words.json.corrupt").exists()
    assert any("invalid" in message.lower() for message in ui.warnings)


def test_save_exported_words_does_not_fallback_to_plain_write(tmp_path):
    path = tmp_path / "exported_words.json"
    path.write_text('{"words": ["bonjour"]}', encoding="utf-8")
    manager = _manager(path)
    manager.exported_words = {"salut"}
    manager.exported_deck_version = "v2"

    with patch("vocab_builder.core.anki_manager.atomic_write_text", side_effect=OSError("disk full")):
        result = manager.save_exported_words()

    assert result is False
    assert path.read_text(encoding="utf-8") == '{"words": ["bonjour"]}'


def test_load_exported_words_handles_unreadable_path_shape(tmp_path):
    path = tmp_path / "exported_words.json"
    path.mkdir()
    ui = _StubUI()

    manager = _manager(path, ui)

    assert manager.exported_words == set()
    assert any("invalid" in message.lower() for message in ui.warnings)


def test_package_fallback_backs_up_existing_deck_before_direct_write(tmp_path, monkeypatch):
    destination = tmp_path / "Deck.apkg"
    destination.write_text("old deck", encoding="utf-8")
    manager = _manager(tmp_path / "exported_words.json")

    class _Package:
        def __init__(self, deck):
            self.deck = deck

        def write_to_file(self, path):
            if Path(path) == destination:
                Path(path).write_text("new deck", encoding="utf-8")

    monkeypatch.setattr(genanki, "Package", _Package)

    package = manager._write_package_atomic(object(), destination, tmp_path)

    assert isinstance(package, _Package)
    assert destination.read_text(encoding="utf-8") == "new deck"
    assert destination.with_suffix(".apkg.bak").read_text(encoding="utf-8") == "old deck"
    snapshots = list(tmp_path.glob("Deck.apkg.*.bak"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == "old deck"
