import unittest

import FrenchVocab


class TestFormatLatexEntry(unittest.TestCase):
    def setUp(self):
        self.formatter = FrenchVocab.FrenchVocabBuilder.format_latex_entry

    def test_escapes_special_chars_in_definitions_and_examples(self):
        word = "cafe"
        wtype = "noun"
        defs = [
            "salt & pepper",
            "100% sure",
            "cost $5 and use #hashtag",
            "snake_case and {brace} and }flip{",
            "approx ~ and ^caret and back\\slash",
        ]
        examples = [
            ("Je mange & bois", "I eat & drink"),
            ("Prix: 100%", "Price is 100%"),
            ("Chemin \\\\", "path \\\\"),
        ]

        out = self.formatter(word, wtype, defs, examples)

        # Check key LaTeX escapes exist
        self.assertIn(r"\&", out)
        self.assertIn(r"\%", out)
        self.assertIn(r"\$", out)
        self.assertIn(r"\#", out)
        self.assertIn(r"\_", out)
        self.assertIn(r"\{", out)
        self.assertIn(r"\}", out)
        self.assertIn(r"\textasciitilde{}", out)
        self.assertIn(r"\textasciicircum{}", out)
        self.assertIn(r"\textbackslash{}", out)

    def test_preserves_parentheses_if_present(self):
        word = "test"
        wtype = "noun"
        defs = ["one"]
        examples = [("Bonjour", "(Hello)")]
        out = self.formatter(word, wtype, defs, examples)
        # Ensure we didn't double-wrap the translation
        self.assertIn("\\\\ (Hello)", out)
        self.assertNotIn("((Hello))", out)

    def test_escapes_word_and_type(self):
        word = "café_crème & croissant"
        wtype = "expr & noun"
        defs = ["d"]
        examples = [("f", "e")]
        out = self.formatter(word, wtype, defs, examples)
        # Word and type appear in the entry header
        self.assertIn(r"\entry{Café\_crème \& croissant}{expr \& noun}", out)

    def test_structure_contains_expected_blocks(self):
        out = self.formatter("mot", "noun", ["def a", "def b"], [("fr 1", "en 1"), ("fr 2", "en 2")])
        self.assertIn(r"\entry{Mot}{noun}", out)
        # The \entry macro supplies enumerate/itemize; invocation only has the argument blocks
        self.assertIn(r"\item def a", out)
        self.assertIn(r"\item fr 1 \\ (en 1)", out)

    def test_square_brackets_are_preserved(self):
        out = self.formatter("mot", "noun", ["[abc]"], [("fr [x]", "en [y]")])
        self.assertIn("[abc]", out)
        self.assertIn("fr [x]", out)
        self.assertIn("en [y]", out)


if __name__ == '__main__':
    unittest.main()
