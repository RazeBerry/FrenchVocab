from pathlib import Path


def test_agent_docs_are_aligned() -> None:
    root = Path(__file__).resolve().parents[1]
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")

    assert agents == claude, "AGENTS.md and CLAUDE.md must remain identical"
