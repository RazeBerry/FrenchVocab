from pathlib import Path
import threading
from unittest.mock import MagicMock, patch

from vocab_builder.core import VocabBuilder
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


def test_update_entry_in_file_prefers_first_duplicate(tmp_path: Path):
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
        ["Updated first"],
        [("Bonjour encore", "Updated")],
        entry_command="\\entry",
    )
    repo.update_entry_in_file("Bonjour", new_block)

    content = repo.latex_file.read_text(encoding="utf-8")
    assert "Old first" not in content
    assert "Old second" in content
    assert "Updated first" in content


def test_load_existing_entries_preserves_exact_duplicates(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.latex_file.write_text(
        r"""\entry{Bonjour}{noun}
      {
        \item First definition
      }
      {
        \item Bonjour \\ (Hello)
      }

\entry{Bonjour}{noun}
      {
        \item Second definition
      }
      {
        \item Bonjour encore \\ (Hello again)
      }
""",
        encoding="utf-8",
    )

    repo.load_existing_entries()

    assert len(repo.word_entries) == 2
    assert repo.word_entries["bonjour"]["definitions_list"] == ["First definition"]
    duplicate_key = repo.duplicate_entry_keys["bonjour"][0]
    assert repo.word_entries[duplicate_key]["definitions_list"] == ["Second definition"]
    assert repo.check_duplicate("bonjour") == "bonjour"


def test_load_existing_entries_preserves_normalized_duplicates(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.latex_file.write_text(
        r"""\entry{Café}{noun}
      {
        \item Accent definition
      }
      {
        \item Café \\ (Coffee)
      }

\entry{Cafe}{noun}
      {
        \item Plain definition
      }
      {
        \item Cafe \\ (Coffee shop)
      }
""",
        encoding="utf-8",
    )

    repo.load_existing_entries()

    assert set(repo.word_entries) == {"café", "cafe"}
    assert repo.check_duplicate("cafe") == "café"


def test_alphabetize_preserves_manual_text_inside_itemize(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.latex_file.write_text(
        r"""\documentclass{article}
\begin{document}
\begin{itemize}[leftmargin=*]
\entry{Zulu}{noun}
  {
    \item Last
  }
  {
    \item Zulu \\ (Zulu)
  }

% manual note that is not a vocabulary entry
\item handwritten note

\entry{Alpha}{noun}
  {
    \item First
  }
  {
    \item Alpha \\ (Alpha)
  }
\end{itemize}
\end{document}
""",
        encoding="utf-8",
    )

    repo.alphabetize_entries()

    content = repo.latex_file.read_text(encoding="utf-8")
    assert "% manual note that is not a vocabulary entry" in content
    assert r"\item handwritten note" in content
    assert content.index(r"\entry{Alpha}") < content.index(r"\entry{Zulu}")
    assert content.count(r"\entry{") == 2


def test_concurrent_inserts_preserve_all_entries(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.latex_file.write_text(
        r"""\documentclass{article}
\begin{document}
\begin{itemize}[leftmargin=*]
\end{itemize}
\end{document}
""",
        encoding="utf-8",
    )

    entries = [
        repo.format_latex_entry("alpha", "noun", ["First"], [("Alpha", "Alpha")]),
        repo.format_latex_entry("zulu", "noun", ["Last"], [("Zulu", "Zulu")]),
    ]
    words = ["alpha", "zulu"]

    threads = [
        threading.Thread(target=repo.insert_entry_alphabetically, args=(entry, word))
        for entry, word in zip(entries, words)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    content = repo.latex_file.read_text(encoding="utf-8")
    assert r"\entry{Alpha}" in content
    assert r"\entry{Zulu}" in content
    assert content.count(r"\entry{") == 2


def test_create_initial_tex_file_does_not_overwrite_existing_file(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.latex_file.write_text("existing saved content", encoding="utf-8")

    repo.create_initial_tex_file()

    assert repo.latex_file.read_text(encoding="utf-8") == "existing saved content"


def test_create_initial_tex_file_restores_backup_when_primary_missing(tmp_path: Path):
    latex_file = tmp_path / "FrenchVocab.tex"
    backup = latex_file.with_suffix(".tex.bak")
    backup.write_text("backup saved content", encoding="utf-8")
    repo = VocabRepository(
        latex_file=latex_file,
        entry_command="\\entry",
        language_config=get_language_config("fr"),
        ui=MagicMock(),
    )

    repo.create_initial_tex_file()

    assert latex_file.read_text(encoding="utf-8") == "backup saved content"


def test_create_initial_tex_file_does_not_replace_failed_backup_restore_with_template(tmp_path: Path):
    latex_file = tmp_path / "FrenchVocab.tex"
    backup = latex_file.with_suffix(".tex.bak")
    backup.write_text("backup saved content", encoding="utf-8")
    repo = VocabRepository(
        latex_file=latex_file,
        entry_command="\\entry",
        language_config=get_language_config("fr"),
        ui=MagicMock(),
    )

    def fail_copy(_source, temp_destination):
        Path(temp_destination).write_text("partial restore", encoding="utf-8")
        raise OSError("simulated restore failure")

    with patch("vocab_builder.core.file_safety.shutil.copy2", side_effect=fail_copy):
        repo.create_initial_tex_file()

    assert not latex_file.exists()
    assert backup.read_text(encoding="utf-8") == "backup saved content"


def test_exported_words_legacy_migration_failure_leaves_no_partial_candidate(tmp_path: Path):
    builder = object.__new__(VocabBuilder)
    builder.language_code = "fr"
    legacy_path = tmp_path / "exported_words_fr.json"
    target_dir = tmp_path / "target"
    candidate = target_dir / "exported_words_fr.json"
    legacy_path.write_text('{"words": ["bonjour"]}', encoding="utf-8")

    def fail_copy(_source, temp_destination):
        Path(temp_destination).write_text("partial migration", encoding="utf-8")
        raise OSError("simulated migration failure")

    with patch("vocab_builder.core.file_safety.shutil.copy2", side_effect=fail_copy):
        resolved = builder._resolve_exported_words_path(tmp_path, target_dir)

    assert resolved == legacy_path
    assert not candidate.exists()
    assert legacy_path.read_text(encoding="utf-8") == '{"words": ["bonjour"]}'
