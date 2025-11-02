import unittest

from languages.anki_shared_styles import BASE_ANKI_CARD_CSS, get_anki_css


class TestAnkiSharedStyles(unittest.TestCase):
    def test_base_css_not_empty(self):
        self.assertGreater(len(BASE_ANKI_CARD_CSS), 100)

    def test_get_anki_css_returns_string(self):
        css = get_anki_css("fr")
        self.assertIsInstance(css, str)
        self.assertGreater(len(css), 100)

    def test_responsive_breakpoints_present(self):
        css = get_anki_css()
        self.assertIn("@media (max-width: 640px)", css)
        self.assertIn("@media print", css)


if __name__ == "__main__":
    unittest.main()
