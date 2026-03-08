from pathlib import Path
from unittest.mock import MagicMock

from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.languages import get_language_config
from vocab_builder.latex_repository import LatexRepository, parse_balanced_group


def _repo(tmp_path: Path) -> VocabRepository:
    latex_file = tmp_path / "FrenchVocab.tex"
    latex_file.write_text("", encoding="utf-8")
    return VocabRepository(
        latex_file=latex_file,
        entry_command="\\entry",
        language_config=get_language_config("fr"),
        ui=MagicMock(),
    )


def test_parse_balanced_group_ignores_escaped_braces():
    content, next_index = parse_balanced_group(r"{alpha \{ beta \} gamma}", 0)

    assert content == r"alpha \{ beta \} gamma"
    assert next_index == len(r"{alpha \{ beta \} gamma}")


def test_repo_round_trips_entries_with_literal_braces(tmp_path: Path):
    repo = _repo(tmp_path)
    entry = repo.format_latex_entry(
        "brace",
        "noun",
        ["value {x}"],
        [("Use {x}", "means {y}")],
        entry_command="\\entry",
    )
    repo.latex_file.write_text(entry, encoding="utf-8")

    repo.load_existing_entries()

    loaded = repo.word_entries["brace"]
    assert loaded["definitions_list"] == ["value \\{x\\}"]
    assert loaded["examples_list"] == [("Use \\{x\\}", "means \\{y\\}")]


def test_load_entries_handles_invalid_utf8_without_crashing(tmp_path: Path):
    path = tmp_path / "bad.tex"
    path.write_bytes(b"\xff\\entry{broken}{noun}{}{}")
    repo = LatexRepository(path)

    entries = repo.load_entries()

    assert len(entries) == 1
    assert entries[0].word == "broken"
    assert any("could not be decoded" in issue for issue in repo.last_load_issues)


def test_update_entry_in_file_prefers_last_duplicate(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.latex_file.write_text(
        r"""\entry{Bonjour}{noun}
      {
        \item Old first
      }
      {
        \item Bonjour \\ (Hello)
      }

\entry{Bonjour}{noun}
      {
        \item Old second
      }
      {
        \item Bonjour encore \\ (Hello again)
      }
""",
        encoding="utf-8",
    )

    new_block = repo.format_latex_entry(
        "Bonjour",
        "noun",
        ["Updated second"],
        [("Bonjour encore", "Updated")],
        entry_command="\\entry",
    )
    repo.update_entry_in_file("Bonjour", new_block)

    content = repo.latex_file.read_text(encoding="utf-8")
    assert "Old first" in content
    assert "Old second" not in content
    assert "Updated second" in content
