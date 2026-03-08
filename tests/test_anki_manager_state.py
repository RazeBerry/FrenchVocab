import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.anki_manager import AnkiExportManager
from languages import get_language_config


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

    with patch("core.anki_manager.atomic_write_text", side_effect=OSError("disk full")):
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
