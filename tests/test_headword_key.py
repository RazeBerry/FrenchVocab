"""The language owns the headword key: identity, order and rail letter.

A config whose key reverses the word sorts "Bravo" (key "ovarb") after "Echo"
(key "ohce"), which the shared accent-folding key never would. Seeing that
order on disk proves the repository asked the config, not the module helper.
"""

from dataclasses import replace
import random
import re

from vocab_builder.core import VocabBuilder
from vocab_builder.languages import get_language_config
from vocab_builder.latex_repository import LatexRepository
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


def _polish_builder(tmp_path, monkeypatch, words):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    tex_path = tmp_path / "PolishVocab.tex"
    entries = "\n\n".join(ENTRY.format(word=word) for word in words)
    tex_path.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\begin{itemize}[leftmargin=*]\n"
        f"{entries}\n\\end{{itemize}}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    builder = VocabBuilder(str(tex_path), provider="gemini", verbose=False, language="pl")
    return builder, tex_path


def test_polish_literal_braces_and_bars_are_not_polish_letters(tmp_path, monkeypatch):
    """The bulk loader accepts "{" and "|", so "Sa{d" and "Z|aba" are new
    words beside "Sąd" and "Żaba", not their duplicates."""
    builder, tex_path = _polish_builder(tmp_path, monkeypatch, ["Sąd", "Żaba"])

    report = builder.add_vocab_entries(
        [
            WordEntry(word=word, type="masculine noun", definitions=["D"], examples=[])
            for word in ("Sa{d", "Z|aba")
        ],
        on_duplicate="error",
    )

    assert [outcome.status for outcome in report.outcomes] == ["added", "added"]
    assert [entry.word for entry in LatexRepository(tex_path).load_entries()] == [
        "Sa{d", "Sąd", "Z|aba", "Żaba",
    ]


def test_polish_letter_files_after_any_mark_on_its_plain_base(tmp_path, monkeypatch):
    """A non-breaking hyphen is valid headword text and sorts above every
    letter, so "A‑klasa" files after "Azot", but still before "Ącki": "a"
    outranks "ą" before the next character is compared."""
    builder, tex_path = _polish_builder(tmp_path, monkeypatch, ["Ącki", "A\u2011klasa", "Azot"])

    builder.alphabetize_entries()

    assert _headwords(tex_path) == ["Azot", "A\u2011klasa", "Ącki"]


def test_polish_key_is_injective_and_keeps_the_polish_order():
    """Distinct NFC lowercase words over Polish letters, their bases, ASCII
    punctuation including the old sentinels, digits and U+2011 never share a
    key: exhaustively up to three characters, then randomly up to ten."""
    key = get_language_config("pl").headword_key
    alphabet = "aąbcćeęlłnńoósśzźżx{|}~09-'\u2011"
    words = [""]
    for length in range(3):
        words += [word + char for word in words if len(word) == length for char in alphabet]
    rng = random.Random(20261118)
    words += ["".join(rng.choices(alphabet, k=rng.randint(4, 10))) for _ in range(20000)]
    words = sorted(set(word for word in words if word))

    keys = {}
    for word in words:
        assert keys.setdefault(key(word), word) == word, (word, keys[key(word)])

    order = ["cud", "ćma", "kawa", "kąt", "los", "łoś", "sad", "sąd", "zupa", "źle", "żaba"]
    assert sorted(reversed(order), key=key) == order
    assert {key(word.upper())[0] for word in ("łoś", "śnieg", "żaba")} == {"l", "s", "z"}
