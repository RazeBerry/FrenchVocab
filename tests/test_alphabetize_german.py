import os
import re
import tempfile
import unittest
from pathlib import Path

import FrenchVocab
from vocab_builder.models import normalize_word_key


GERMAN_ENTRY_TEMPLATE = r"""\entry{{{word}}}{{noun}}
      {{
        \item Definition for {word}
      }}
      {{
        \item Beispiel für {word} \\ (Example for {word})
      }}"""


class TestGermanAlphabetization(unittest.TestCase):
    def setUp(self):
        os.environ["GEMINI_API_KEY"] = "AIza" + "x" * 36

    def _create_tex(self, words, directory: Path) -> Path:
        entries = "\n\n".join(GERMAN_ENTRY_TEMPLATE.format(word=w) for w in words)
        content = (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\begin{itemize}[leftmargin=*]\n"
            f"{entries}\n"
            "\\end{itemize}\n"
            "\\end{document}\n"
        )
        tex_path = directory / "GermanVocab.tex"
        tex_path.write_text(content, encoding="utf-8")
        return tex_path

    def test_alphabetize_entries_orders_umlauts_and_eszet(self):
        unsorted_words = ["Übung", "Ahorn", "Öl", "Über", "Ähre", "Strand", "Straße"]
        expected_order = ["Ähre", "Ahorn", "Öl", "Strand", "Straße", "Über", "Übung"]

        with tempfile.TemporaryDirectory() as td:
            tmp_dir = Path(td)
            tex_path = self._create_tex(unsorted_words, tmp_dir)

            builder = FrenchVocab.FrenchVocabBuilder(
                str(tex_path), provider="gemini", verbose=False, language="de"
            )
            builder.alphabetize_entries()

            content = tex_path.read_text(encoding="utf-8")
            words_in_file = re.findall(r"\\entry\{([^}]*)\}", content)

            self.assertEqual(words_in_file, expected_order)

    def test_normalize_word_key_expands_german_characters(self):
        word_map = {
            "Ähre": "aehre",
            "Öl": "oel",
            "Über": "ueber",
            "Straße": "strasse",
        }
        for raw, expected in word_map.items():
            self.assertEqual(normalize_word_key(raw), expected)


if __name__ == "__main__":
    unittest.main()
