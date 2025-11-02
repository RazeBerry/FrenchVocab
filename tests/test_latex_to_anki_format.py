import re
import unittest

import sys
import os
sys.path.append(os.path.dirname(__file__))
from _stubs import install_basic_stubs
install_basic_stubs()

import FrenchVocab  # noqa: E402


class TestLatexToAnki(unittest.TestCase):
    def setUp(self):
        self.builder = object.__new__(FrenchVocab.FrenchVocabBuilder)

    def test_latex_to_anki_format_basic(self):
        text = (
            "\\item Premier point\\n"
            "\\item Deuxième point\\n"
            "Texte en \\textbf{gras} avec une ligne\\\\ et encore.\n"
        )
        out = FrenchVocab.FrenchVocabBuilder.latex_to_anki_format(self.builder, text)
        # Items stripped and wrapped in semantic list markup, LaTeX commands removed, newlines -> <br>
        self.assertIn('<ul class="entry-list">', out)
        items = re.findall(r"<li>(.*?)</li>", out)
        self.assertIn('Premier point', items)
        self.assertIn('Deuxième point', items)
        self.assertNotIn('textbf', out)
        self.assertIn('<br>', out)

    def test_latex_to_anki_handles_empty(self):
        out = FrenchVocab.FrenchVocabBuilder.latex_to_anki_format(self.builder, "")
        self.assertEqual(out, "")

    def test_latex_to_anki_preserves_macro_content(self):
        text = "\\item Texte en \\textbf{gras} et \\emph{italique}"
        out = FrenchVocab.FrenchVocabBuilder.latex_to_anki_format(self.builder, text)
        items = re.findall(r"<li>(.*?)</li>", out)
        self.assertEqual(items, ['Texte en gras et italique'])


if __name__ == '__main__':
    unittest.main()
