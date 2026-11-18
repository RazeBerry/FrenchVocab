"""The language owns the headword key: identity, order and rail letter.

A config whose key reverses the word sorts "Bravo" (key "ovarb") after "Echo"
(key "ohce"), which the shared accent-folding key never would. Seeing that
order on disk proves the repository asked the config, not the module helper.
"""

from dataclasses import replace
import re

from vocab_builder.core import VocabBuilder
from vocab_builder.languages import get_language_config
from vocab_builder.models import WordEntry, normalize_word_key

REVERSED_FRENCH = replace(
    get_language_config("fr"),
    headword_key=lambda word: normalize_word_key(word)[::-1],
)

ENTRY = r"""\entry{{{word}}}{{noun}}
      {{
        \item Definition for {word}
      }}
      {{
        \item Exemple pour {word} \\ (Example for {word})
      }}"""


def _headwords(tex_path):
    return re.findall(r"\\entry\{([^}]*)\}", tex_path.read_text(encoding="utf-8"))


def test_alphabetize_and_insert_follow_the_language_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    tex_path = tmp_path / "FrenchVocab.tex"
    entries = "\n\n".join(ENTRY.format(word=word) for word in ("Alpha", "Bravo", "Delta", "Echo"))
    tex_path.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\begin{itemize}[leftmargin=*]\n"
        f"{entries}\n\\end{{itemize}}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    builder = VocabBuilder(
        str(tex_path), provider="gemini", verbose=False, language_config=REVERSED_FRENCH
    )

    builder.alphabetize_entries()
    assert _headwords(tex_path) == ["Alpha", "Delta", "Echo", "Bravo"]

    report = builder.add_vocab_entries(
        [WordEntry(word="Kilo", type="noun", definitions=["K"], examples=[])],
        on_duplicate="error",
    )
    assert report.count("added") == 1
    assert _headwords(tex_path) == ["Alpha", "Delta", "Echo", "Kilo", "Bravo"]


def test_polish_alphabetize_files_each_polish_letter_after_its_base(tmp_path, monkeypatch):
    """Polish order: a before ą, l before ł, z before ź before ż, and a
    diacritic letter's words after every plain-letter word ("kawa", "kąt")."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    expected = ["Cud", "Ćma", "Kawa", "Kąt", "Los", "Łoś", "Sad", "Sąd", "Zupa", "Źle", "Żaba"]
    shuffled = ["Żaba", "Sąd", "Kawa", "Łoś", "Cud", "Źle", "Sad", "Zupa", "Kąt", "Ćma", "Los"]
    tex_path = tmp_path / "PolishVocab.tex"
    entries = "\n\n".join(ENTRY.format(word=word) for word in shuffled)
    tex_path.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\begin{itemize}[leftmargin=*]\n"
        f"{entries}\n\\end{{itemize}}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    builder = VocabBuilder(str(tex_path), provider="gemini", verbose=False, language="pl")

    builder.alphabetize_entries()

    assert _headwords(tex_path) == expected
