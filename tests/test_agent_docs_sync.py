from pathlib import Path

from scripts.sync_agent_docs import agent_docs_are_synced, sync_agent_docs


def test_agent_docs_are_aligned() -> None:
    root = Path(__file__).resolve().parents[1]
    agents = (root / "AGENTS.md").read_bytes()
    claude = (root / "CLAUDE.md").read_bytes()

    assert agents == claude, "AGENTS.md and CLAUDE.md must remain identical"


def test_sync_agent_docs_rebuilds_the_mirror(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_bytes(b"canonical knowledge\n")
    (tmp_path / "CLAUDE.md").write_bytes(b"stale knowledge\n")

    assert not agent_docs_are_synced(tmp_path)
    assert sync_agent_docs(tmp_path)
    assert agent_docs_are_synced(tmp_path)
    assert not sync_agent_docs(tmp_path)
