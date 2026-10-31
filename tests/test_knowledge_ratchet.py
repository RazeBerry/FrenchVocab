import datetime as dt
import json
import subprocess
from pathlib import Path

from scripts.knowledge_ratchet import BASELINE_NAME, check, main, measure

ROOT = Path(__file__).resolve().parents[1]


def test_repository_holds_the_ratchet() -> None:
    assert check(ROOT) == []


def _repo(tmp_path: Path) -> Path:
    """A minimal repository: an instruction file, one router, one contract, one report."""
    files = {
        "AGENTS.md": "# Guide\n\nStart at `docs/core_map.md`.\n",
        "docs/core_map.md": "# Router\n\n| To | Read |\n|---|---|\n| store | `docs/store.md` |\n",
        "docs/store.md": "# Store\n\n- Writes are atomic (`reports/kind/2026-01-01_atomic.md`).\n",
        "reports/kind/2026-01-01_atomic.md": "# Evidence\n",
    }
    for name, body in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / BASELINE_NAME).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / BASELINE_NAME).write_text(json.dumps(measure(tmp_path)), encoding="utf-8")
    return tmp_path


def test_clean_fixture_holds(tmp_path: Path) -> None:
    assert check(_repo(tmp_path)) == []


def test_growing_the_instruction_file_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
        handle.write("- One more rule that belongs in a contract.\n")
    assert check(root) == ["instruction_file_lines: 4 > 3"]
    assert main(["--root", str(root), "--check"]) == 1


def test_an_unlinked_contract_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "docs/orphan.md").write_text("# Nobody routes here\n", encoding="utf-8")
    assert "unreachable_documents: 1 > 0" in check(root)


def test_a_report_linked_only_from_another_report_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "reports/kind/2026-02-01_followup.md").write_text(
        "Corrects `reports/kind/2026-01-01_atomic.md`.\n", encoding="utf-8"
    )
    assert "unreachable_documents: 1 > 0" in check(root)


def test_a_link_to_a_missing_document_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with (root / "docs/store.md").open("a", encoding="utf-8") as handle:
        handle.write("See `docs/gone.md`.\n")
    assert "broken_links: 1 > 0" in check(root)


def test_git_ignored_notes_are_not_knowledge(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("docs/local/\n", encoding="utf-8")
    (root / "docs/local").mkdir()
    (root / "docs/local/scratch.md").write_text("# private\n", encoding="utf-8")
    assert check(root) == []


def test_proposals_need_an_owner_and_an_unexpired_sunset(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "docs/proposals").mkdir()
    (root / "docs/proposals/idea.md").write_text(
        "---\nowner: maintainer\nsunset: 2026-03-01\n---\n# Idea\n", encoding="utf-8"
    )
    with (root / "docs/core_map.md").open("a", encoding="utf-8") as handle:
        handle.write("| explore | `docs/proposals/idea.md` |\n")
    assert check(root, today=dt.date(2026, 2, 1)) == []
    assert check(root, today=dt.date(2026, 3, 2)) == ["unowned_or_expired_proposals: 1 > 0"]
