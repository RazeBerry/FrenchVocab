from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib
import json
import sqlite3
import sys
import zipfile
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from vocab_builder.anki_exporter import AnkiExportEntry, AnkiExporter
import vocab_builder.anki_exporter as anki_module
from vocab_builder.core import VocabBuilder
from vocab_builder.core.anki_identity import identity_path, load_identity, save_identity
from vocab_builder.core.vocab_corrections import CorrectionError, run_corrections
from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.languages import get_language_config
from vocab_builder.latex_repository import LatexRepository, find_entry_bounds
from vocab_builder.models import WordEntry


def entry(word: str, definition: str = "A cat", word_type: str = "noun") -> dict:
    return {
        "word": word, "type": word_type, "definitions": [definition],
        "examples": [[f"Le {word.lower()} dort.", "The cat sleeps."]],
    }


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def fixture(
    tmp_path: Path, *, words: tuple[str, ...] = ("Chat", "Chien", "Ânerie"), language: str = "fr",
) -> dict:
    config = get_language_config(language)
    vocab = tmp_path / config.vocab_filename
    blocks = [VocabRepository.format_latex_entry(
        row["word"], row["type"], row["definitions"],
        [tuple(pair) for pair in row["examples"]], config.vocab.entry_command,
    ) for row in (entry(word) for word in words)]
    vocab.write_text("\\begin{document}\n" + "\n\n".join(blocks) + "\n\\end{document}\n", encoding="utf-8")
    tracker = tmp_path / f"exported_words_{language}.json"
    tracker.write_text(json.dumps({
        "words": [word.lower() for word in words],
        "entry_order": [word.lower() for word in words],
        "deck_version": "v1", "last_export": {"deck_name": "Test"}, "extra": "kept",
    }) + "\n", encoding="utf-8")
    identity = identity_path(tracker, language)
    history = tmp_path / "history" / f"{language}_translations.jsonl"
    return {
        "root": tmp_path, "language": language, "vocab": vocab, "tracker": tracker,
        "identity": identity, "history": history,
    }


def patch_for(paths: dict, rows: list[dict], patch_id: str = "fr-test-a") -> Path:
    patch = paths["root"] / "patch.json"
    patch.write_text(json.dumps({
        "version": 1, "language": paths["language"], "patch_id": patch_id,
        "base": {
            "vocab_sha256": digest(paths["vocab"]),
            "tracker_sha256": digest(paths["tracker"]),
            "identity_sha256": digest(paths["identity"]),
        },
        "corrections": rows,
    }, ensure_ascii=False), encoding="utf-8")
    return patch


def correction(before: dict, after: dict, *, retire: list[dict] | None = None, keep: str | None = None) -> dict:
    row = {
        "id": "fr-0001", "before": before, "after": after,
        "retire": retire or [], "reasons": ["Reviewed correction"],
        "sources": ["https://example.org/dictionary"],
    }
    if keep is not None:
        row["keep_identity_of"] = keep
    return row


def run(paths: dict, patch: Path, *, apply: bool = False) -> dict:
    return run_corrections(
        language=paths["language"], data_dir=paths["root"], patch_path=patch, apply=apply
    )


def parsed_words(paths: dict) -> list[str]:
    return [item.word for item in LatexRepository(paths["vocab"]).load_entries()]


def test_dry_run_writes_no_data_and_shows_diffs(tmp_path):
    paths = fixture(tmp_path)
    patch = patch_for(paths, [correction(entry("Chat"), entry("Chat", "A feline"))])
    before = {name: digest(paths[name]) for name in ("vocab", "tracker", "identity", "history")}
    report = run(paths, patch)
    assert report["status"] == "validated"
    assert "A feline" in report["corrections"][0]["entry_diff"]
    assert report["bundle_path"] is None
    assert before == {name: digest(paths[name]) for name in before}
    assert not (tmp_path / "backups").exists()


def test_sha_and_before_mismatch_refuse_without_data_changes(tmp_path):
    paths = fixture(tmp_path)
    patch = patch_for(paths, [correction(entry("Chat"), entry("Chat", "A feline"))])
    paths["vocab"].write_text(paths["vocab"].read_text() + "% concurrent\n")
    with pytest.raises(CorrectionError, match="Base SHA-256 mismatch"):
        run(paths, patch, apply=True)
    assert not paths["identity"].exists()
    assert not paths["history"].exists()
    patch = patch_for(paths, [correction(entry("Chat", "Wrong"), entry("Chat", "A feline"))])
    with pytest.raises(CorrectionError, match="before/retire mismatch"):
        run(paths, patch, apply=True)


def test_in_place_correction_and_untouched_blocks(tmp_path):
    paths = fixture(tmp_path)
    original = paths["vocab"].read_text()
    untouched = {
        word: original[slice(*find_entry_bounds(original, r"\entry", word))]
        for word in ("Chien", "Ânerie")
    }
    patch = patch_for(paths, [correction(entry("Chat"), entry("Chat", "A feline"))])
    report = run(paths, patch, apply=True)
    assert report["counts"] == {"before": 3, "after": 3, "retired": 0}
    assert parsed_words(paths) == ["Chat", "Chien", "Ânerie"]
    updated = paths["vocab"].read_text()
    for word, block in untouched.items():
        assert updated[slice(*find_entry_bounds(updated, r"\entry", word))] == block
    assert (tmp_path / "backups" / "corrections").exists()
    assert paths["vocab"].with_suffix(".tex.bak").exists()


def test_rename_preserves_root_seed_and_tracker_state(tmp_path):
    # Stored collections are alphabetical by the accent-free key, so the
    # renamed entry must land in that order, not at the old entry's slot.
    paths = fixture(tmp_path, words=("Ânerie", "Chat", "Chien"))
    patch = patch_for(paths, [correction(entry("Chat"), entry("Minou"))])
    report = run(paths, patch, apply=True)
    assert parsed_words(paths) == ["Ânerie", "Chien", "Minou"]
    assert load_identity(paths["identity"]) == {"minou": "chat"}
    tracker = json.loads(paths["tracker"].read_text())
    assert tracker["entry_order"] == ["ânerie", "minou", "chien"]
    assert tracker["words"] == ["chien", "minou", "ânerie"]
    assert tracker["extra"] == "kept"
    assert tracker["deck_version"] == "v1"
    assert report["retired_anki_identities"] == []
    second = patch_for(paths, [correction(entry("Minou"), entry("Félin"))], "fr-test-b")
    run(paths, second, apply=True)
    assert load_identity(paths["identity"]) == {"félin": "chat"}


def test_case_only_rename_adds_no_alias(tmp_path):
    paths = fixture(tmp_path)
    patch = patch_for(paths, [correction(entry("Chat"), entry("CHat"))])
    run(paths, patch, apply=True)
    assert "CHat" in parsed_words(paths)
    assert load_identity(paths["identity"]) == {}


def _note_guid(word: str, aliases: dict[str, str], language: str = "fr") -> str:
    config = get_language_config(language).anki
    exporter = AnkiExporter("Test", replace(config, guid_headword_aliases=aliases))
    original = anki_module.genanki
    anki_module.genanki = SimpleNamespace(Note=lambda **kwargs: SimpleNamespace(**kwargs))
    try:
        note = exporter._build_note(
            AnkiExportEntry(word=word, word_type="noun", definitions=["A cat"], examples=[]),
            object(), fallback_order=0,
        )
    finally:
        anki_module.genanki = original
    return note.guid


def test_merge_retire_keeps_selected_identity_and_reports_other_note(tmp_path):
    paths = fixture(tmp_path, words=("Chat", "Minou", "Chien"))
    tracker = json.loads(paths["tracker"].read_text())
    tracker["words"] = ["minou", "chien"]
    paths["tracker"].write_text(json.dumps(tracker))
    old_kept_guid = _note_guid("Minou", {})
    old_retired_guid = _note_guid("Chat", {})
    patch = patch_for(paths, [correction(
        entry("Chat"), entry("Félin"), retire=[entry("Minou")], keep="Minou",
    )])
    report = run(paths, patch, apply=True)
    assert _note_guid("Félin", load_identity(paths["identity"])) == old_kept_guid
    assert report["retired_anki_identities"] == [{"headword": "Chat", "guid": old_retired_guid}]
    updated = json.loads(paths["tracker"].read_text())
    assert updated["entry_order"] == ["félin", "chien"]
    assert updated["words"] == ["chien", "félin"]
    assert report["selected_words"] == ["Félin"]


def test_collision_and_shared_seed_refuse(tmp_path):
    paths = fixture(tmp_path)
    patch = patch_for(paths, [correction(entry("Chat"), entry("Chien"))])
    with pytest.raises(CorrectionError, match="collides"):
        run(paths, patch, apply=True)
    # A live "chat" beside an alias to "chat" is a reintroduced spelling and
    # gets its own seed; two aliases naming one seed have no such repair.
    save_identity(paths["identity"], {"chien": "chat", "ânerie": "chat"})
    patch = patch_for(paths, [correction(entry("Chat"), entry("Chat", "A feline"))])
    with pytest.raises(CorrectionError, match="share an Anki GUID"):
        run(paths, patch)


def test_collision_ignoring_accents_refuses(tmp_path):
    """The app treats "Anerie" and "Ânerie" as one word, so a rename onto the
    accent-free spelling of another live entry must refuse, not store twins."""
    paths = fixture(tmp_path)
    patch = patch_for(paths, [correction(entry("Chat"), entry("Anerie"))])
    before = paths["vocab"].read_bytes()
    with pytest.raises(CorrectionError, match="collides"):
        run(paths, patch, apply=True)
    assert paths["vocab"].read_bytes() == before



def test_polish_correction_keeps_diacritics_as_identity(tmp_path):
    """Under the Polish key "sąd" (court) and "sad" (orchard) are two words:
    a rename to "SAD" beside a live "Sad" collides, a rename to "Sąd" does not,
    and the renamed entry files right after "Sad"."""
    paths = fixture(tmp_path, words=("Kot", "Sad", "Zupa"), language="pl")
    patch = patch_for(paths, [correction(entry("Kot"), entry("SAD"))])
    with pytest.raises(CorrectionError, match="collides"):
        run(paths, patch, apply=True)

    patch = patch_for(paths, [correction(entry("Kot"), entry("Sąd", "A court"))])
    report = run(paths, patch, apply=True)

    assert report["status"] == "applied"
    assert parsed_words(paths) == ["Sad", "Sąd", "Zupa"]

def _exported_guids(paths: dict, name: str) -> dict[str, str]:
    """Export the whole collection through the real builder and genanki."""
    builder = VocabBuilder(
        str(paths["vocab"]), provider="gemini", verbose=False, language=paths["language"],
    )
    package = paths["root"] / f"{name}.apkg"
    builder.export_to_anki(include_exported_words=True, output_path=package)
    with zipfile.ZipFile(package) as archive:
        database = paths["root"] / f"{name}.sqlite"
        database.write_bytes(archive.read("collection.anki2"))
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT flds, guid FROM notes").fetchall()
    return {fields.split("\x1f")[0]: guid for fields, guid in rows}


def test_reintroduced_spelling_gets_its_own_anki_note(tmp_path, monkeypatch):
    """"Sad" entered for "court" is corrected to "Sąd" and keeps its note.
    A genuine "Sad" (orchard) added later must not take that note's GUID,
    and keeps the fresh one after the court entry is retired."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    stub_genanki = sys.modules.pop("genanki")
    try:
        real_genanki = importlib.import_module("genanki")
    finally:
        sys.modules["genanki"] = stub_genanki
    monkeypatch.setitem(sys.modules, "genanki", real_genanki)
    monkeypatch.setattr(anki_module, "genanki", real_genanki)

    paths = fixture(tmp_path, words=("Kot", "Sad"), language="pl")
    court_guid = _exported_guids(paths, "first")["Sad"]

    patch = patch_for(paths, [correction(entry("Sad"), entry("Sąd", "A court"))], "pl-a")
    run(paths, patch, apply=True)
    orchard = WordEntry(word="Sad", type="masculine noun", definitions=["An orchard"], examples=[])
    builder = VocabBuilder(str(paths["vocab"]), provider="gemini", verbose=False, language="pl")
    assert builder.add_vocab_entries([orchard], on_duplicate="error").count("added") == 1

    guids = _exported_guids(paths, "second")
    assert guids["Sąd"] == court_guid
    assert guids["Sad"] != court_guid
    assert load_identity(paths["identity"]) == {"sąd": "sad", "sad": "sad#2"}

    patch = patch_for(paths, [correction(
        entry("Kot"), entry("Kot", "A cat"), retire=[entry("Sąd", "A court")], keep="Kot",
    )], "pl-b")
    report = run(paths, patch, apply=True)
    assert report["retired_anki_identities"] == [{"headword": "Sąd", "guid": court_guid}]
    assert _exported_guids(paths, "third")["Sad"] == guids["Sad"]


def test_correction_reserves_a_reintroduced_spelling_before_export(tmp_path):
    """A correction can run before any export has seen a reintroduced "Sad".
    It reserves that word's seed first, skipping "sad#2", which the renamed
    earlier reintroduction "Sadek" still holds, and retiring "Sąd" reports the
    court note's GUID, not the orchard's."""
    paths = fixture(tmp_path, words=("Kot", "Sad", "Sadek", "Sąd"), language="pl")
    save_identity(paths["identity"], {"sąd": "sad", "sadek": "sad#2"})
    court_guid = _note_guid("Sąd", load_identity(paths["identity"]), "pl")

    patch = patch_for(paths, [correction(
        entry("Kot"), entry("Kot", "A cat"), retire=[entry("Sąd")], keep="Kot",
    )], "pl-c")
    report = run(paths, patch, apply=True)

    assert load_identity(paths["identity"]) == {"sadek": "sad#2", "sad": "sad#3"}
    assert report["retired_anki_identities"] == [{"headword": "Sąd", "guid": court_guid}]


def test_correct_history_once_and_acquisition_unchanged(tmp_path):
    paths = fixture(tmp_path)
    patch = patch_for(paths, [correction(entry("Chat"), entry("Chat", "A feline"))])
    first = run(paths, patch, apply=True)
    second = run(paths, patch, apply=True)
    assert second["status"] == "already_applied"
    records = [json.loads(line) for line in paths["history"].read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["action"] == "correct"
    assert records[0]["metadata"]["patch_id"] == "fr-test-a"
    assert json.loads(paths["tracker"].read_text())["entry_order"] == ["chat", "chien", "ânerie"]
    assert first["status"] == "applied"


def test_pending_mobile_transactions_refuse_but_previews_do_not(tmp_path):
    paths = fixture(tmp_path)
    state = tmp_path / ".mobile-fr-state.json"
    state.write_text(json.dumps({"version": 1, "previews": {"p": {}}, "transactions": {"t": {}}}))
    patch = patch_for(paths, [correction(entry("Chat"), entry("Chat", "A feline"))])
    with pytest.raises(CorrectionError, match="Pending mobile transactions"):
        run(paths, patch, apply=True)
    state.write_text(json.dumps({"version": 1, "previews": {"p": {}}, "transactions": {}}))
    assert run(paths, patch)["status"] == "validated"


class _QuietUI:
    def success(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def _concurrent_add(data_dir: str, ready, go, result) -> None:
    paths = Path(data_dir)
    config = get_language_config("fr")
    repo = VocabRepository(
        paths / config.vocab_filename, config.vocab.entry_command, config, _QuietUI(),
    )
    repo.ensure_entries_loaded()  # stale independent instance before apply
    ready.set()
    go.wait(10)
    block = VocabRepository.format_latex_entry("Lapin", "noun", ["A rabbit"], [], r"\entry")
    result.put(repo.insert_entry_alphabetically(block, "Lapin"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX file locking required")
def test_stale_process_writer_never_loses_a_successful_mutation(tmp_path):
    paths = fixture(tmp_path)
    patch = patch_for(paths, [correction(entry("Chat"), entry("Chat", "A feline"))])
    ctx = multiprocessing.get_context("fork")
    ready, go, result = ctx.Event(), ctx.Event(), ctx.Queue()
    process = ctx.Process(target=_concurrent_add, args=(str(tmp_path), ready, go, result))
    process.start()
    try:
        assert ready.wait(10)
        go.set()
        try:
            run(paths, patch, apply=True)
            correction_applied = True
        except CorrectionError as exc:
            assert "Base SHA-256 mismatch" in str(exc)
            correction_applied = False
        assert result.get(timeout=10) is True
    finally:
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join()
    assert process.exitcode == 0
    assert "Lapin" in parsed_words(paths)
    if correction_applied:
        assert "A feline" in paths["vocab"].read_text()
