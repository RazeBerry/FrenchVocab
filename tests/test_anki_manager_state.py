import importlib
import json
import sqlite3
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import genanki
import pytest

import vocab_builder.anki_exporter as anki_exporter_module
from vocab_builder.anki_exporter import AnkiExporter, AnkiExportEntry
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


def test_default_output_path_uses_export_state_directory_not_cwd(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    manager = _manager(state_dir / "exported_words.json")
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    assert manager._normalize_output_path("French Vocabulary") == (
        state_dir / "anki_exports" / "French Vocabulary.apkg"
    ).resolve()
    assert manager._normalize_output_path("anki/French Vocabulary") == (
        state_dir / "anki_exports" / "anki" / "French Vocabulary.apkg"
    ).resolve()


def test_operator_export_directory_overrides_state_location(tmp_path, monkeypatch):
    configured = tmp_path / "server-exports"
    monkeypatch.setenv("VOCABBUILDER_ANKI_EXPORT_DIR", str(configured))

    manager = _manager(tmp_path / "state" / "exported_words.json")

    assert manager._normalize_output_path("French Vocabulary") == (
        configured / "French Vocabulary.apkg"
    ).resolve()


def test_operator_export_directory_rejects_absolute_paths_outside_root(
    tmp_path,
    monkeypatch,
):
    configured = tmp_path / "server-exports"
    monkeypatch.setenv("VOCABBUILDER_ANKI_EXPORT_DIR", str(configured))
    manager = _manager(tmp_path / "state" / "exported_words.json")

    with pytest.raises(ValueError, match="configured export directory"):
        manager._normalize_output_path(tmp_path / "outside" / "Deck.apkg")

    inside = configured / "nested" / "Deck.apkg"
    assert manager._normalize_output_path(inside) == inside.resolve()


def test_absolute_output_path_is_still_honored(tmp_path):
    manager = _manager(tmp_path / "exported_words.json")
    destination = tmp_path / "custom" / "Deck.apkg"

    assert manager._normalize_output_path(destination) == destination.resolve()


def test_relative_output_path_cannot_escape_export_directory(tmp_path):
    manager = _manager(tmp_path / "exported_words.json")

    try:
        manager._normalize_output_path("../Deck")
    except ValueError as exc:
        assert "inside" in str(exc)
    else:
        raise AssertionError("path traversal should be rejected")


def test_legacy_cwd_metadata_path_is_normalized_to_default_export_dir(tmp_path):
    cwd_path = tmp_path / "old-cwd" / "French Vocabulary.apkg"
    state_path = tmp_path / "exported_words.json"
    state_path.write_text(
        json.dumps(
            {
                "words": [],
                "last_export": {
                    "deck_name": "French Vocabulary",
                    "path": str(cwd_path),
                    "export_context": "incremental",
                },
            }
        ),
        encoding="utf-8",
    )

    manager = _manager(state_path)

    assert manager.last_export_metadata is not None
    expected_path = (tmp_path / "anki_exports" / "French Vocabulary.apkg").resolve()
    assert manager.last_export_metadata["path"] == str(expected_path)
    assert manager.last_export_metadata["path_source"] == "default"


def _vocab_entry(word: str) -> dict[str, object]:
    return {
        "word": word.capitalize(),
        "type": "noun",
        "definitions_list": [f"Definition of {word}"],
        "examples_list": [(f"Example with {word}.", "Plain explanation.")],
    }


def _mistake_record(attempt_id: str, user_text: str) -> dict[str, object]:
    return {
        "attempt_id": attempt_id,
        "language": "fr",
        "mode": "forward",
        "user_text": user_text,
        "corrected_text": f"Corrected {user_text}",
        "english_gloss": "English intent",
        "corrections": [{"why": f"Why {attempt_id}"}],
    }


def test_anki_order_is_deterministic_but_not_latex_alphabetical(tmp_path):
    repo = _StubRepo()
    repo.word_entries = {
        word: _vocab_entry(word)
        for word in ("alpha", "beta", "delta", "epsilon", "gamma", "zulu")
    }
    path = tmp_path / "exported_words.json"
    manager = AnkiExportManager(
        ui=_StubUI(),
        language_config=get_language_config("fr"),
        vocab_repo=repo,  # type: ignore[arg-type]
        exported_words_file=path,
        project_root=tmp_path,
    )

    entries = manager._collect_entries_for_export(
        word_entries=repo.word_entries,
        selected_words=None,
        include_all=True,
        all_exported_words=set(),
    )
    exported_order = [item[0] for item in entries]

    assert exported_order == ["gamma", "zulu", "epsilon", "delta", "alpha", "beta"]
    assert exported_order != sorted(exported_order)
    assert [item[2].order for item in entries] == list(range(1, 7))

    assert manager.save_exported_words() is True
    reloaded = AnkiExportManager(
        ui=_StubUI(),
        language_config=get_language_config("fr"),
        vocab_repo=repo,  # type: ignore[arg-type]
        exported_words_file=path,
        project_root=tmp_path,
    )
    assert list(reloaded.entry_order) == exported_order


def test_written_apkg_uses_due_for_order_and_headword_for_sort_field(
    tmp_path,
    monkeypatch,
):
    stub_genanki = sys.modules.pop("genanki")
    try:
        real_genanki = importlib.import_module("genanki")
    finally:
        sys.modules["genanki"] = stub_genanki
    monkeypatch.setattr(anki_exporter_module, "genanki", real_genanki)

    config = get_language_config("en")
    exporter = AnkiExporter(config.anki.default_deck_name, config.anki)
    deck = exporter.build_deck(
        [
            AnkiExportEntry(
                word="Recondite",
                word_type="adjective",
                definitions=["Difficult to understand."],
                examples=[("A recondite argument.", "An obscure argument.")],
                order=17,
            )
        ]
    )
    package_path = tmp_path / "EnglishDeck.apkg"
    real_genanki.Package(deck).write_to_file(str(package_path))

    extraction_dir = tmp_path / "package"
    with zipfile.ZipFile(package_path) as archive:
        database_path = Path(archive.extract("collection.anki2", extraction_dir))

    with sqlite3.connect(database_path) as connection:
        due = connection.execute("SELECT due FROM cards").fetchone()[0]
        sort_field = connection.execute("SELECT sfld FROM notes").fetchone()[0]

    assert due == 17
    assert sort_field == "Recondite"


def test_new_entries_append_to_persistent_anki_acquisition_order(tmp_path):
    repo = _StubRepo()
    repo.word_entries = {"legacy": _vocab_entry("legacy")}
    path = tmp_path / "exported_words.json"
    manager = AnkiExportManager(
        ui=_StubUI(),
        language_config=get_language_config("en"),
        vocab_repo=repo,  # type: ignore[arg-type]
        exported_words_file=path,
        project_root=tmp_path,
    )

    repo.word_entries["recondite"] = _vocab_entry("recondite")
    manager.register_entry_order("recondite")
    repo.word_entries["cynosure"] = _vocab_entry("cynosure")
    manager.register_entry_order("cynosure")

    assert manager.entry_order[-2:] == ("recondite", "cynosure")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["entry_order"][-2:] == ["recondite", "cynosure"]


def test_sync_entry_order_with_no_available_entries_preserves_persisted_order(tmp_path):
    manager = _manager(tmp_path / "exported_words.json")
    manager._entry_order = ["alpha", "beta"]

    manager._sync_entry_order({})

    assert manager.entry_order == ("alpha", "beta")


def test_collect_entries_skips_stale_order_keys_with_gapless_due_order(tmp_path):
    repo = _StubRepo()
    repo.word_entries = {
        "alpha": _vocab_entry("alpha"),
        "beta": _vocab_entry("beta"),
    }
    manager = AnkiExportManager(
        ui=_StubUI(),
        language_config=get_language_config("fr"),
        vocab_repo=repo,  # type: ignore[arg-type]
        exported_words_file=tmp_path / "exported_words.json",
        project_root=tmp_path,
    )
    manager._entry_order = ["missing", "alpha", "beta"]
    manager._sync_entry_order = lambda _entries: None  # type: ignore[method-assign]

    entries = manager._collect_entries_for_export(
        word_entries=repo.word_entries,
        selected_words=None,
        include_all=True,
        all_exported_words=set(),
    )

    assert [item[0] for item in entries] == ["alpha", "beta"]
    assert [item[2].order for item in entries] == [1, 2]


def test_export_to_anki_reports_empty_vocabulary_without_writing(tmp_path):
    repo = _StubRepo()
    repo.word_entries = {}
    tracker = tmp_path / "exported_words.json"
    tracker.write_text(
        json.dumps({"words": [], "deck_version": None, "entry_order": ["alpha"]}),
        encoding="utf-8",
    )
    ui = _StubUI()
    manager = AnkiExportManager(
        ui=ui,
        language_config=get_language_config("fr"),
        vocab_repo=repo,  # type: ignore[arg-type]
        exported_words_file=tracker,
        project_root=tmp_path,
    )
    output_path = tmp_path / "empty.apkg"

    manager.export_to_anki("Empty", output_path=output_path, quiet=True)

    assert not output_path.exists()
    assert any(
        "there are no vocabulary entries to export" in message.lower()
        for message in ui.warnings
    )


def test_registering_first_word_ever_sets_acquisition_order(tmp_path):
    repo = _StubRepo()
    repo.word_entries = {"thatword": _vocab_entry("thatword")}
    manager = AnkiExportManager(
        ui=_StubUI(),
        language_config=get_language_config("en"),
        vocab_repo=repo,  # type: ignore[arg-type]
        exported_words_file=tmp_path / "exported_words.json",
        project_root=tmp_path,
    )

    manager.register_entry_order("thatword")

    assert manager.entry_order == ("thatword",)
    payload = json.loads(manager.exported_words_file.read_text(encoding="utf-8"))
    assert payload["entry_order"] == ["thatword"]


def test_history_recovers_acquisition_order_before_first_export(tmp_path):
    repo = _StubRepo()
    repo.word_entries = {
        "alpha": _vocab_entry("alpha"),
        "zulu": _vocab_entry("zulu"),
    }
    records = [
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "flow": "vocab",
            "action": "new",
            "word": "zulu",
        },
        {
            "timestamp": "2026-01-02T00:00:00+00:00",
            "flow": "vocab",
            "action": "new",
            "word": "alpha",
        },
    ]
    manager = AnkiExportManager(
        ui=_StubUI(),
        language_config=get_language_config("fr"),
        vocab_repo=repo,  # type: ignore[arg-type]
        exported_words_file=tmp_path / "exported_words.json",
        project_root=tmp_path,
        entry_history_reader=lambda: records,
    )

    entries = manager._collect_entries_for_export(
        word_entries=repo.word_entries,
        selected_words=None,
        include_all=True,
        all_exported_words=set(),
    )

    assert [item[0] for item in entries] == ["zulu", "alpha"]


def test_export_includes_mistake_deck_when_requested(tmp_path, monkeypatch):
    class _Package:
        payloads = []

        def __init__(self, deck_or_decks):
            self.payloads.append(deck_or_decks)

        def write_to_file(self, path):
            Path(path).write_bytes(b"stub apkg")

    monkeypatch.setattr(genanki, "Package", _Package)
    history_path = tmp_path / "fr_compositions.jsonl"
    history_path.write_text(
        json.dumps(_mistake_record("attempt-1", "Je aller.")) + "\n",
        encoding="utf-8",
    )
    repo = _StubRepo()
    repo.word_entries = {"alpha": _vocab_entry("alpha")}
    manager = AnkiExportManager(
        ui=_StubUI(),
        language_config=get_language_config("fr"),
        vocab_repo=repo,  # type: ignore[arg-type]
        exported_words_file=tmp_path / "exported_words.json",
        project_root=tmp_path,
        composition_history_paths=[history_path],
    )

    manager.export_to_anki(
        "French Vocabulary",
        include_exported_words=True,
        include_mistake_deck=True,
        quiet=True,
    )

    assert isinstance(_Package.payloads[-1], list)
    assert len(_Package.payloads[-1]) == 2
    assert manager.exported_words == {"alpha"}


def test_retired_snapshot_fields_load_silently_and_are_dropped_on_save(tmp_path):
    """Trackers written before 2026-09-22 still carry the clean-exit snapshot fields."""
    state_path = tmp_path / "exported_words.json"
    state_path.write_text(
        json.dumps(
            {
                "words": ["alpha"],
                "deck_version": "v1",
                "entry_order": ["alpha"],
                "snapshot_hash": "0" * 64,
                "snapshot_export": {
                    "deck_name": "French Vocabulary",
                    "path": str(tmp_path / "French Vocabulary.apkg"),
                    "include_mistake_deck": True,
                },
            }
        ),
        encoding="utf-8",
    )
    ui = _StubUI()

    manager = _manager(state_path, ui)

    assert ui.warnings == []
    assert ui.errors == []
    assert manager.exported_words == {"alpha"}
    assert manager.exported_deck_version == "v1"
    assert manager.save_exported_words()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert "snapshot_hash" not in payload
    assert "snapshot_export" not in payload
    assert payload["words"] == ["alpha"]
    assert payload["entry_order"] == ["alpha"]
