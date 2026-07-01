import json
import uuid
from pathlib import Path

import genanki

from vocab_builder.core.anki_manager import AnkiExportManager
from vocab_builder.languages import get_language_config


class _StubUI:
    def __init__(self, *, confirm_result=True):
        self.confirm_result = confirm_result
        self.confirm_calls = []
        self.warnings = []
        self.infos = []
        self.panels = []

    def confirm(self, message, default=True):
        self.confirm_calls.append((message, default))
        return self.confirm_result

    def warning(self, message, *args, **kwargs):  # noqa: ARG002
        self.warnings.append(message)

    def info(self, message, *args, **kwargs):  # noqa: ARG002
        self.infos.append(message)

    def error(self, message, *args, **kwargs):  # noqa: ARG002
        raise AssertionError(message)

    def panel(self, content, *args, **kwargs):  # noqa: ARG002
        self.panels.append(content)


class _NoConfirmUI(_StubUI):
    def confirm(self, message, default=True):  # noqa: ARG002
        raise AssertionError("confirm should be hidden when no mistake history exists")


class _Repo:
    def __init__(self):
        self.word_entries = {
            "bonjour": {
                "word": "Bonjour",
                "type": "noun",
                "definitions_list": ["hello"],
                "examples_list": [("Bonjour.", "Hello.")],
            }
        }

    def ensure_entries_loaded(self):
        return None

    def get_all_latex_entries(self):
        return set(self.word_entries)


def _install_genanki_capture(monkeypatch):
    class _Model:
        def __init__(self, model_id, name, fields, templates, css):
            self.model_id = model_id
            self.name = name
            self.fields = fields
            self.templates = templates
            self.css = css

    class _Deck:
        def __init__(self, deck_id, name):
            self.deck_id = deck_id
            self.name = name
            self.notes = []

        def add_note(self, note):
            self.notes.append(note)

    class _Note:
        def __init__(self, model, guid, fields):
            self.model = model
            self.guid = guid
            self.fields = fields

    class _Package:
        payloads = []

        def __init__(self, deck_or_decks):
            self.deck_or_decks = deck_or_decks
            _Package.payloads.append(deck_or_decks)

        def write_to_file(self, path):
            Path(path).write_bytes(b"stub apkg")

    monkeypatch.setattr(genanki, "Model", _Model)
    monkeypatch.setattr(genanki, "Deck", _Deck)
    monkeypatch.setattr(genanki, "Note", _Note)
    monkeypatch.setattr(genanki, "Package", _Package)
    return _Package


def _manager(tmp_path, history_path, ui=None):
    return AnkiExportManager(
        ui=ui or _StubUI(),
        language_config=get_language_config("fr"),
        vocab_repo=_Repo(),  # type: ignore[arg-type]
        exported_words_file=tmp_path / "exported_words.json",
        project_root=tmp_path,
        composition_history_paths=[history_path],
    )


def _write_history(path, records):
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _record(**overrides):
    record = {
        "attempt_id": "attempt-1",
        "ts": "2026-06-12T10:00:00Z",
        "mode": "use_words",
        "language": "fr",
        "target_words": ["verser"],
        "source_english": None,
        "reference_target": None,
        "english_gloss": "I spilled the glass.",
        "user_text": "Je goss le verre.",
        "corrected_text": "J'ai renverse le verre.",
        "corrections": [
            {
                "from": "goss",
                "to": "renverse",
                "why": "The attempted verb is not idiomatic French.",
                "alternative": "J'ai fait tomber le verre.",
            }
        ],
        "word_verdicts": {"verser": "incorrect"},
        "unknown_candidates": [],
        "provider": "Fake Gemini",
        "session_id": "session-1",
    }
    record.update(overrides)
    return record


def _export_with_mistakes(manager, tmp_path):
    manager.export_to_anki(
        "French Vocabulary",
        include_exported_words=True,
        output_path=tmp_path / "French Vocabulary.apkg",
        include_mistake_deck=True,
    )


def _mistake_deck(package_payload):
    assert isinstance(package_payload, list)
    matching = [deck for deck in package_payload if deck.name == "FrenchDeck::Mistakes"]
    assert len(matching) == 1
    return matching[0]


def test_mistake_deck_uses_one_model_with_fix_and_produce_templates(tmp_path, monkeypatch):
    package_cls = _install_genanki_capture(monkeypatch)
    history = tmp_path / "fr_compositions.jsonl"
    _write_history(
        history,
        [
            _record(
                corrections=[
                    {"from": "goss", "to": "renverse", "why": "Use a real French verb."},
                    {"from": "le", "to": "un", "why": "The article is more natural here."},
                ]
            )
        ],
    )

    _export_with_mistakes(_manager(tmp_path, history), tmp_path)

    deck = _mistake_deck(package_cls.payloads[-1])
    assert deck.name == "FrenchDeck::Mistakes"
    assert len(deck.notes) == 2
    assert len({id(note.model) for note in deck.notes}) == 1

    templates = deck.notes[0].model.templates
    assert [template["name"] for template in templates] == ["Fix-this", "Produce-this"]
    assert "Find the error(s)" in templates[0]["qfmt"]
    assert "{{FlawedText}}" in templates[0]["qfmt"]
    assert "{{#EnglishIntent}}" in templates[1]["qfmt"]
    assert "{{CorrectedText}}" in templates[1]["afmt"]


def test_mistake_guid_is_deterministic_across_reexports(tmp_path, monkeypatch):
    package_cls = _install_genanki_capture(monkeypatch)
    history = tmp_path / "fr_compositions.jsonl"
    _write_history(history, [_record(attempt_id="attempt-guid")])
    manager = _manager(tmp_path, history)

    _export_with_mistakes(manager, tmp_path)
    first_guid = _mistake_deck(package_cls.payloads[-1]).notes[0].guid
    _export_with_mistakes(manager, tmp_path)
    second_guid = _mistake_deck(package_cls.payloads[-1]).notes[0].guid

    expected = uuid.uuid5(
        uuid.NAMESPACE_URL,
        "FrenchDeck::mistake::attempt-guid::0",
    ).hex
    assert first_guid == expected
    assert second_guid == expected


def test_mistake_fields_use_gloss_and_reverse_source(tmp_path, monkeypatch):
    package_cls = _install_genanki_capture(monkeypatch)
    history = tmp_path / "fr_compositions.jsonl"
    _write_history(
        history,
        [
            _record(attempt_id="use-words"),
            _record(
                attempt_id="reverse",
                mode="reverse",
                source_english="The rain is falling.",
                english_gloss=None,
                user_text="La pluie chute.",
                corrected_text="La pluie tombe.",
                corrections=[
                    {
                        "from": "chute",
                        "to": "tombe",
                        "why": "Tomber is the idiomatic verb for rain.",
                    }
                ],
            ),
        ],
    )

    _export_with_mistakes(_manager(tmp_path, history), tmp_path)

    notes = _mistake_deck(package_cls.payloads[-1]).notes
    use_words_note = notes[0]
    reverse_note = notes[1]
    assert use_words_note.fields == [
        "Je goss le verre.",
        "J'ai renverse le verre.",
        "The attempted verb is not idiomatic French.",
        "I spilled the glass.",
    ]
    assert reverse_note.fields == [
        "La pluie chute.",
        "La pluie tombe.",
        "Tomber is the idiomatic verb for rain.",
        "The rain is falling.",
    ]


def test_missing_gloss_keeps_fix_card_and_suppresses_produce_card(tmp_path, monkeypatch):
    package_cls = _install_genanki_capture(monkeypatch)
    history = tmp_path / "fr_compositions.jsonl"
    _write_history(history, [_record(english_gloss=None)])

    _export_with_mistakes(_manager(tmp_path, history), tmp_path)

    deck = _mistake_deck(package_cls.payloads[-1])
    note = deck.notes[0]
    assert note.fields[0] == "Je goss le verre."
    assert note.fields[1] == "J'ai renverse le verre."
    assert note.fields[2] == "The attempted verb is not idiomatic French."
    assert note.fields[3] == ""
    assert "Find the error(s)" in note.model.templates[0]["qfmt"]
    assert "{{#EnglishIntent}}" in note.model.templates[1]["qfmt"]


def test_no_history_hides_mistake_toggle(tmp_path):
    history = tmp_path / "missing_fr_compositions.jsonl"
    ui = _NoConfirmUI()
    manager = _manager(tmp_path, history, ui=ui)

    assert manager._prompt_include_mistake_deck() is False
