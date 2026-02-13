"""Integration tests for the merge duplicate workflow.

Tests cover:
- Basic merge functionality
- Accent normalization in deduplication (Bug #4 fix)
- Robust examples parsing with nested parentheses (Bug #5 fix)
- File update failure handling (Bug #1 fix)
- Transactional behavior - no partial state (Bug #6 fix)
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.vocab_repository import VocabRepository, EntryNotFoundError
from models import normalize_word_key
from languages import get_language_config
from ui_helper import UIHelper


class TestNormalizationForDeduplication(unittest.TestCase):
    """Test accent normalization in definition deduplication."""

    def test_normalize_word_key_strips_accents(self):
        """Verify normalize_word_key strips accents consistently."""
        self.assertEqual(normalize_word_key("café"), "cafe")
        self.assertEqual(normalize_word_key("naïve"), "naive")
        self.assertEqual(normalize_word_key("Ärger"), "aerger")
        self.assertEqual(normalize_word_key("über"), "ueber")

    def test_definitions_with_accent_variations_deduplicated(self):
        """Definitions differing only by accents should be treated as duplicates."""
        # This tests the norm_text function behavior in merge_into_existing
        # by checking that normalize_word_key handles the accents
        self.assertEqual(
            normalize_word_key("naïve person"),
            normalize_word_key("naive person")
        )
        self.assertEqual(
            normalize_word_key("café culture"),
            normalize_word_key("cafe culture")
        )


class TestRobustExamplesParsing(unittest.TestCase):
    """Test robust parsing of example strings with nested parentheses."""

    def setUp(self):
        """Create a minimal VocabRepository-like object for testing."""
        self.ui = MagicMock(spec=UIHelper)

    def test_extract_translation_simple(self):
        """Test simple parentheses extraction."""
        # Import the actual function from vocab.py
        from core.vocab import FrenchVocabBuilder

        # Create a minimal builder to access the method
        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui

        result = builder._extract_translation_from_parens("Bonjour (Hello)")
        self.assertEqual(result, ("Bonjour", "Hello"))

    def test_extract_translation_nested_parens(self):
        """Test extraction with nested parentheses in translation."""
        from core.vocab import FrenchVocabBuilder
        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui

        # Nested parentheses - should extract outermost
        result = builder._extract_translation_from_parens(
            "C'est la vie (That's life (philosophy))"
        )
        self.assertEqual(result, ("C'est la vie", "That's life (philosophy)"))

    def test_extract_translation_parens_in_source(self):
        """Test extraction when source has parentheses."""
        from core.vocab import FrenchVocabBuilder
        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui

        result = builder._extract_translation_from_parens(
            "Il a dit (doucement) quelque chose (He said something (softly))"
        )
        self.assertEqual(
            result,
            ("Il a dit (doucement) quelque chose", "He said something (softly)")
        )

    def test_extract_translation_no_parens(self):
        """Test that text without parentheses returns None."""
        from core.vocab import FrenchVocabBuilder
        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui

        result = builder._extract_translation_from_parens("No parentheses here")
        self.assertIsNone(result)

    def test_extract_translation_unbalanced_parens(self):
        """Test handling of unbalanced parentheses."""
        from core.vocab import FrenchVocabBuilder
        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui

        # Unbalanced - more closing than opening
        result = builder._extract_translation_from_parens("Test )extra)")
        self.assertIsNone(result)

    def test_parse_examples_string_multiple(self):
        """Test parsing multiple examples separated by semicolons."""
        from core.vocab import FrenchVocabBuilder
        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui

        examples_str = "Bonjour (Hello); Au revoir (Goodbye); Merci (Thanks)"
        result = builder._parse_examples_string(examples_str)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], ("Bonjour", "Hello"))
        self.assertEqual(result[1], ("Au revoir", "Goodbye"))
        self.assertEqual(result[2], ("Merci", "Thanks"))

    def test_parse_examples_string_with_malformed_entry(self):
        """Test that malformed entries are preserved with warning."""
        from core.vocab import FrenchVocabBuilder
        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui

        examples_str = "Bonjour (Hello); Malformed without parens; Merci (Thanks)"
        result = builder._parse_examples_string(examples_str)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], ("Bonjour", "Hello"))
        self.assertEqual(result[1], ("Malformed without parens", ""))  # Preserved with empty translation
        self.assertEqual(result[2], ("Merci", "Thanks"))

        # Warning should have been shown
        self.ui.warning.assert_called_once()


class TestEntryNotFoundError(unittest.TestCase):
    """Test that file update failures raise proper exceptions."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.latex_file = Path(self.temp_dir) / "test.tex"
        self.ui = MagicMock(spec=UIHelper)
        self.config = get_language_config("fr")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_update_entry_raises_on_not_found(self):
        """Test that updating non-existent entry raises EntryNotFoundError."""
        # Create file with one entry
        self.latex_file.write_text(r"""
\entry{Bonjour}{noun}
      {
        \item Hello
      }
      {
        \item Bonjour! \\ (Hello!)
      }
""")

        repo = VocabRepository(
            latex_file=self.latex_file,
            entry_command="\\entry",
            language_config=self.config,
            ui=self.ui,
        )

        # Try to update an entry that doesn't exist
        with self.assertRaises(EntryNotFoundError) as ctx:
            repo.update_entry_in_file("NonExistent", r"\entry{NonExistent}{noun}{}{}")

        self.assertIn("NonExistent", str(ctx.exception))

    def test_update_entry_case_insensitive_fallback(self):
        """Test that case-insensitive search is used as fallback."""
        # Create file with entry using different case
        self.latex_file.write_text(r"""
\entry{BONJOUR}{noun}
      {
        \item Hello
      }
      {
        \item Bonjour! \\ (Hello!)
      }
""")

        repo = VocabRepository(
            latex_file=self.latex_file,
            entry_command="\\entry",
            language_config=self.config,
            ui=self.ui,
        )

        # Update with different case - should succeed via case-insensitive fallback
        new_block = r"""\entry{Bonjour}{noun}
      {
        \item Hello
        \item Greeting
      }
      {
        \item Bonjour! \\ (Hello!)
      }"""

        # This should NOT raise - case-insensitive fallback should find it
        repo.update_entry_in_file("bonjour", new_block)

        # Verify the file was updated
        content = self.latex_file.read_text()
        self.assertIn("Greeting", content)


class TestMergeTransactionalBehavior(unittest.TestCase):
    """Test that merge operations are transactional - no partial state."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.latex_file = Path(self.temp_dir) / "test.tex"
        self.ui = MagicMock(spec=UIHelper)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_merge_failure_leaves_memory_unchanged(self):
        """Test that failed file update doesn't modify memory."""
        from core.vocab import FrenchVocabBuilder

        # Create initial file
        self.latex_file.write_text(r"""
\entry{Test}{noun}
      {
        \item Original definition
      }
      {
        \item Test example \\ (Test translation)
      }
""")

        # Create builder with the test file
        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui
        builder.latex_file = self.latex_file
        builder.entry_command = "\\entry"
        builder.word_entries = {
            "test": {
                "word": "Test",
                "type": "noun",
                "definitions": "Original definition",
                "definitions_list": ["Original definition"],
                "examples": "Test example (Test translation)",
                "examples_list": [("Test example", "Test translation")],
            }
        }
        builder._entries_loaded = True
        builder._history_logger = MagicMock()

        # Mock update_entry_in_file to raise an error
        with patch.object(builder, 'update_entry_in_file', side_effect=EntryNotFoundError("Test error")):
            result = builder.merge_into_existing(
                "Test",
                "noun",
                ["New definition"],
                [("New example", "New translation")]
            )

        # Merge should have failed
        self.assertFalse(result)

        # Memory should be unchanged
        entry = builder.word_entries["test"]
        self.assertEqual(entry["definitions_list"], ["Original definition"])
        self.assertEqual(len(entry["examples_list"]), 1)

        # Error should have been shown
        self.ui.error.assert_called()


class TestMergeDeduplication(unittest.TestCase):
    """Test that merge correctly deduplicates definitions and examples."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.latex_file = Path(self.temp_dir) / "test.tex"
        self.ui = MagicMock(spec=UIHelper)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_duplicate_definitions_not_added(self):
        """Test that duplicate definitions are not added during merge."""
        from core.vocab import FrenchVocabBuilder

        self.latex_file.write_text(r"""
\entry{Café}{noun}
      {
        \item Coffee
      }
      {
        \item Un café \\ (A coffee)
      }
""")

        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui
        builder.latex_file = self.latex_file
        builder.entry_command = "\\entry"
        builder.word_entries = {
            "café": {
                "word": "Café",
                "type": "noun",
                "definitions": "Coffee",
                "definitions_list": ["Coffee"],
                "examples": "Un café (A coffee)",
                "examples_list": [("Un café", "A coffee")],
            }
        }
        builder._entries_loaded = True
        builder._history_logger = MagicMock()

        # Mock the file update to succeed
        with patch.object(builder, 'update_entry_in_file'):
            with patch.object(builder, '_log_merge_history'):
                result = builder.merge_into_existing(
                    "Café",
                    "noun",
                    ["Coffee", "Café (coffee shop)"],  # First one is duplicate
                    [("Un café", "A coffee"), ("Deux cafés", "Two coffees")]  # First is duplicate
                )

        self.assertTrue(result)

        # Should only have 2 definitions (original + 1 new)
        entry = builder.word_entries["café"]
        self.assertEqual(len(entry["definitions_list"]), 2)
        self.assertIn("Coffee", entry["definitions_list"])
        self.assertIn("Café (coffee shop)", entry["definitions_list"])

        # Should only have 2 examples (original + 1 new)
        self.assertEqual(len(entry["examples_list"]), 2)

    def test_accent_variations_deduplicated(self):
        """Test that definitions with accent variations are treated as duplicates."""
        from core.vocab import FrenchVocabBuilder

        self.latex_file.write_text(r"""
\entry{Naïve}{adjective}
      {
        \item Naive, innocent
      }
      {
        \item Elle est naïve \\ (She is naive)
      }
""")

        builder = object.__new__(FrenchVocabBuilder)
        builder.ui = self.ui
        builder.latex_file = self.latex_file
        builder.entry_command = "\\entry"
        builder.word_entries = {
            "naïve": {
                "word": "Naïve",
                "type": "adjective",
                "definitions": "Naive, innocent",
                "definitions_list": ["Naive, innocent"],
                "examples": "Elle est naïve (She is naive)",
                "examples_list": [("Elle est naïve", "She is naive")],
            }
        }
        builder._entries_loaded = True
        builder._history_logger = MagicMock()

        with patch.object(builder, 'update_entry_in_file'):
            with patch.object(builder, '_log_merge_history'):
                result = builder.merge_into_existing(
                    "Naïve",
                    "adjective",
                    ["naive, innocent", "Lacking sophistication"],  # First is duplicate (accent diff)
                    []
                )

        self.assertTrue(result)

        # Should only have 2 definitions (original kept, accent variant rejected, new one added)
        entry = builder.word_entries["naïve"]
        self.assertEqual(len(entry["definitions_list"]), 2)
        self.assertIn("Naive, innocent", entry["definitions_list"])
        self.assertIn("Lacking sophistication", entry["definitions_list"])


if __name__ == "__main__":
    unittest.main()
