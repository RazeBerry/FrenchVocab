import unittest
from dataclasses import replace

from vocab_builder.languages import get_language_config
from vocab_builder.languages.anki_shared_styles import BASE_ANKI_CARD_CSS, get_anki_css
from vocab_builder.languages.base import AnkiCardTemplate


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

    def test_version_id_changes_with_template_and_css(self):
        anki = get_language_config("fr").anki
        changed_card = replace(
            anki,
            card_templates=(AnkiCardTemplate("Card 1", "front updated", "back"),),
        )
        changed_css = replace(anki, card_css=anki.card_css + "\n.x {}")
        self.assertNotEqual(anki.version_id, changed_card.version_id)
        self.assertNotEqual(anki.version_id, changed_css.version_id)

if __name__ == "__main__":
    unittest.main()
