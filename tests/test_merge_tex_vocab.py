"""The standalone two-file merge reads generated files with the repository parser and key."""

from pathlib import Path

import pytest

from scripts import merge_tex_vocab
from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.languages import get_language_config
from vocab_builder.latex_repository import iter_entry_groups, unescape_latex


def _write_collection(path: Path, language: str, words: list[str]) -> Path:
    vocab = get_language_config(language).vocab
    entries = "".join(
        VocabRepository.format_latex_entry(
            word, "masculine noun", [f"Meaning of {word}."], [(word, "Example.")]
        )
        + "\n\n"
        for word in words
    )
    path.write_text(vocab.initial_content + "\n" + entries + vocab.final_content, encoding="utf-8")
    return path


def _merge(tmp_path: Path, language: str, first: list[str], second: list[str]) -> str:
    one = _write_collection(tmp_path / "one.tex", language, first)
    two = _write_collection(tmp_path / "two.tex", language, second)
    merge_tex_vocab.main(["--language", language, str(one), str(two)])
    [merged] = tmp_path.glob("one_merged_*.tex")
    return merged.read_text(encoding="utf-8")


def _headwords(content: str) -> list[str]:
    return [
        unescape_latex(groups[0].strip())
        for groups, _, _ in iter_entry_groups(content, "\\entry", num_groups=4)
    ]


def test_polish_merge_keeps_sad_and_sad_with_ogonek_and_the_entry_macro(tmp_path):
    vocab = get_language_config("pl").vocab
    merged = _merge(tmp_path, "pl", ["Sad"], ["Sąd"])
    assert _headwords(merged) == ["Sad", "Sąd"]
    # The preamble, whose \entry definition holds its own itemize and #4, is
    # carried over byte for byte.
    assert merged.startswith(vocab.initial_content)
    assert merged.endswith(vocab.final_content)


def test_french_merge_treats_cote_with_and_without_accent_as_one_entry(tmp_path):
    merged = _merge(tmp_path, "fr", ["Côte"], ["Abri", "cote"])
    assert _headwords(merged) == ["Abri", "Côte"]


def test_merge_requires_the_collection_language(tmp_path):
    one = _write_collection(tmp_path / "one.tex", "pl", ["Sad"])
    two = _write_collection(tmp_path / "two.tex", "pl", ["Sąd"])
    with pytest.raises(SystemExit) as excinfo:
        merge_tex_vocab.main([str(one), str(two)])
    assert excinfo.value.code == 2
    assert not list(tmp_path.glob("one_merged_*.tex"))
