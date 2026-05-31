import json
from pathlib import Path
from unittest.mock import MagicMock

from scripts import bulk_add as bulk_add_script
from vocab_builder.core.bulk_add import bulk_add_entries
from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.languages import get_language_config
from vocab_builder.models import WordEntry


def _repo(tmp_path: Path) -> VocabRepository:
    config = get_language_config("fr")
    latex_file = tmp_path / config.vocab_filename
    latex_file.write_text(
        config.vocab.initial_content + config.vocab.final_content,
        encoding="utf-8",
    )
    return VocabRepository(
        latex_file=latex_file,
        entry_command=config.vocab.entry_command,
        language_config=config,
        ui=MagicMock(),
        vocab_template=config.vocab,
    )


def _entry(
    word: str,
    *,
    word_type: str = "noun",
    definitions: list[str] | None = None,
    examples: list[tuple[str, str]] | None = None,
) -> WordEntry:
    return WordEntry(
        word=word,
        type=word_type,
        definitions=definitions or [f"{word} definition"],
        examples=examples or [(f"{word} source", f"{word} english")],
    )


def _snapshot_backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.*.bak"))


def test_bulk_add_commits_one_sorted_batch_with_one_backup_event(tmp_path: Path):
    repo = _repo(tmp_path)
    original = repo.latex_file.read_text(encoding="utf-8")

    report = bulk_add_entries(repo, [_entry("zulu"), _entry("alpha")])

    assert report.ok
    assert report.count("added") == 2
    content = repo.latex_file.read_text(encoding="utf-8")
    assert content.index(r"\entry{Alpha}") < content.index(r"\entry{Zulu}")
    assert repo.latex_file.with_suffix(".tex.bak").read_text(encoding="utf-8") == original
    snapshots = _snapshot_backups(repo.latex_file)
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == original


def test_bulk_add_second_skip_run_is_idempotent_and_writes_nothing(tmp_path: Path):
    repo = _repo(tmp_path)
    bulk_add_entries(repo, [_entry("alpha")])
    content_after_first = repo.latex_file.read_text(encoding="utf-8")
    backups_after_first = {
        repo.latex_file.with_suffix(".tex.bak"),
        *_snapshot_backups(repo.latex_file),
    }

    report = bulk_add_entries(repo, [_entry("alpha")], on_duplicate="skip")

    assert report.ok
    assert report.count("skipped") == 1
    assert repo.latex_file.read_text(encoding="utf-8") == content_after_first
    backups_after_second = {
        repo.latex_file.with_suffix(".tex.bak"),
        *_snapshot_backups(repo.latex_file),
    }
    assert backups_after_second == backups_after_first


def test_bulk_add_duplicate_error_blocks_entire_batch(tmp_path: Path):
    repo = _repo(tmp_path)
    bulk_add_entries(repo, [_entry("bonjour")])
    original = repo.latex_file.read_text(encoding="utf-8")
    original_backups = list(_snapshot_backups(repo.latex_file))

    report = bulk_add_entries(
        repo,
        [_entry("bonjour"), _entry("zulu")],
        on_duplicate="error",
    )

    assert not report.ok
    assert report.count("failed") == 2
    assert repo.latex_file.read_text(encoding="utf-8") == original
    assert _snapshot_backups(repo.latex_file) == original_backups
    assert r"\entry{Zulu}" not in repo.latex_file.read_text(encoding="utf-8")


def test_bulk_add_merge_updates_existing_entry_in_single_commit(tmp_path: Path):
    repo = _repo(tmp_path)
    bulk_add_entries(repo, [_entry("bonjour", definitions=["Hello"], examples=[("Bonjour", "Hello")])])

    report = bulk_add_entries(
        repo,
        [_entry("bonjour", definitions=["Good day"], examples=[("Bonjour a tous", "Hello everyone")])],
        on_duplicate="merge",
    )

    assert report.ok
    assert report.count("merged") == 1
    content = repo.latex_file.read_text(encoding="utf-8")
    assert "Hello" in content
    assert "Good day" in content
    assert content.count(r"\entry{Bonjour}") == 1


def test_bulk_add_dry_run_does_not_write_or_backup(tmp_path: Path):
    repo = _repo(tmp_path)
    original = repo.latex_file.read_text(encoding="utf-8")

    report = bulk_add_entries(repo, [_entry("alpha")], dry_run=True)

    assert report.ok
    assert report.dry_run
    assert report.count("added") == 1
    assert repo.latex_file.read_text(encoding="utf-8") == original
    assert not repo.latex_file.with_suffix(".tex.bak").exists()
    assert _snapshot_backups(repo.latex_file) == []


def test_bulk_add_empty_batch_is_noop(tmp_path: Path):
    repo = _repo(tmp_path)
    original = repo.latex_file.read_text(encoding="utf-8")

    report = bulk_add_entries(repo, [])

    assert report.ok
    assert report.outcomes == []
    assert repo.latex_file.read_text(encoding="utf-8") == original


def test_bulk_add_cli_validation_collects_errors_without_mutation(tmp_path: Path, capsys):
    repo = _repo(tmp_path)
    original = repo.latex_file.read_text(encoding="utf-8")
    payload = {
        "language": "fr",
        "entries": [
            {"word": "", "definitions": []},
            {"word": "valide", "definitions": ["Valid"], "examples": [["source", 3]]},
        ],
    }
    json_file = tmp_path / "entries.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")

    code = bulk_add_script.main(
        ["--language", "fr", "--base-dir", str(tmp_path), "--file", str(json_file)]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "entries[0].word" in captured.err
    assert "entries[0].definitions" in captured.err
    assert "entries[1].examples[0][1]" in captured.err
    assert repo.latex_file.read_text(encoding="utf-8") == original


def test_bulk_add_cli_json_report(tmp_path: Path, capsys):
    _repo(tmp_path)
    payload = {
        "language": "fr",
        "entries": [
            {
                "word": "verser",
                "type": "verb",
                "definitions": ["To pour"],
                "examples": [["Elle verse le cafe.", "She pours the coffee."]],
            }
        ],
    }
    json_file = tmp_path / "entries.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")

    code = bulk_add_script.main(
        [
            "--language",
            "fr",
            "--base-dir",
            str(tmp_path),
            "--file",
            str(json_file),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert code == 0
    assert report["ok"] is True
    assert report["counts"]["added"] == 1
