import re
import unittest

import FrenchVocab


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

    def test_latex_to_anki_filters_brace_lines(self):
        text = "\\item to menace\n\\item }\n\\item to imperil"
        out = FrenchVocab.FrenchVocabBuilder.latex_to_anki_format(self.builder, text)
        items = re.findall(r"<li>(.*?)</li>", out)
        self.assertNotIn('}', items)
        self.assertEqual(items, ['to menace', 'to imperil'])

    def test_latex_to_anki_strips_nested_commands(self):
        text = "\\item Example with \\textbf{outer \\emph{inner} emphasis}"
        out = FrenchVocab.FrenchVocabBuilder.latex_to_anki_format(self.builder, text)
        items = re.findall(r"<li>(.*?)</li>", out)
        self.assertEqual(items, ['Example with outer inner emphasis'])
        self.assertNotIn('}', out)

    def test_latex_to_anki_escapes_html(self):
        text = "\\item <script>alert(1)</script> & \\textbf{bold}"
        out = FrenchVocab.FrenchVocabBuilder.latex_to_anki_format(self.builder, text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)
        self.assertIn("&amp;", out)
        self.assertNotIn("<script>", out)


if __name__ == '__main__':
    unittest.main()
