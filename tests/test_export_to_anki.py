import os
import tempfile
import types
import unittest
from pathlib import Path

from vocab_builder.core import VocabBuilder
import genanki
from vocab_builder.languages.french import FRENCH_CONFIG


class _StubUI:
    def __init__(self):
        self.messages = []

    def panel(self, *args, **kwargs):
        pass

    def success(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        self.messages.append(("error", args, kwargs))


class TestExportToAnki(unittest.TestCase):
    def setUp(self):
        self._orig_model = genanki.Model
        self._orig_deck = genanki.Deck
        self._orig_note = genanki.Note
        self._orig_package = genanki.Package

        class _Model:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class _Deck:
            def __init__(self, deck_id, name):
                self.deck_id = deck_id
                self.name = name
                self.notes = []

            def add_note(self, note):
                self.notes.append(note)

        class _Note:
            def __init__(self, model, guid, fields):
                self.model = model
                self.guid = guid
                self.fields = fields

        class _Package:
            last_written_path = None
            last_deck = None

            def __init__(self, deck):
                _Package.last_deck = deck

            def write_to_file(self, path):
                _Package.last_written_path = path

        genanki.Model = _Model
        genanki.Deck = _Deck
        genanki.Note = _Note
        genanki.Package = _Package

        self.package_cls = _Package

    def tearDown(self):
        genanki.Model = self._orig_model
        genanki.Deck = self._orig_deck
        genanki.Note = self._orig_note
        genanki.Package = self._orig_package

    def test_export_to_anki_exports_new_words_and_updates_tracking(self):
        builder = object.__new__(VocabBuilder)
        builder.ui = _StubUI()
        builder.console = types.SimpleNamespace()
        builder.word_entries = {
            'bonjour': {
                'word': 'Bonjour',
                'type': 'noun',
                'definitions': 'Salut amical; Forme polie',
                'definitions_list': ['Salut amical', 'Forme polie'],
                'examples': 'Bonjour tout le monde (Hello everyone)',
                'examples_list': [('Bonjour tout le monde', 'Hello everyone')],
            },
            'salut': {
                'word': 'Salut',
                'type': 'noun',
                'definitions': 'Informel',
                'definitions_list': ['Informel'],
                'examples': 'Salut ! (Hi!)',
                'examples_list': [('Salut !', 'Hi!')],
            },
        }
        builder.exported_words = {'salut'}
        builder.exported_deck_version = None
        builder.save_exported_words = lambda: None

        with tempfile.TemporaryDirectory() as tmp:
            builder.exported_words_file = os.path.join(tmp, 'exported_words.json')
            builder.export_to_anki('Test Deck')

        package = self.package_cls
        self.assertIsNotNone(package.last_written_path)
        self.assertTrue(package.last_written_path.endswith('.apkg'))
        deck = package.last_deck
        self.assertIsNotNone(deck)
        self.assertEqual(deck.name, 'Test Deck')
        self.assertEqual(len(deck.notes), 1)

        note = deck.notes[0]
        self.assertEqual(note.fields[0], 'Bonjour')
        self.assertEqual(note.fields[1], 'noun')
        self.assertEqual(note.fields[2], '<ul class=\"entry-list\"><li>Salut amical</li><li>Forme polie</li></ul>')
        self.assertEqual(note.fields[3], '<ul class=\"entry-list\"><li>Bonjour tout le monde (Hello everyone)</li></ul>')

        self.assertIn('bonjour', builder.exported_words)
        self.assertIn('salut', builder.exported_words)
        self.assertEqual(builder.exported_deck_version, FRENCH_CONFIG.anki.version_id)

    def test_export_selected_words_only(self):
        builder = object.__new__(VocabBuilder)
        builder.ui = _StubUI()
        builder.console = types.SimpleNamespace()
        builder.word_entries = {
            'bonjour': {
                'word': 'Bonjour',
                'type': 'noun',
                'definitions': 'Salut amical; Forme polie',
                'definitions_list': ['Salut amical', 'Forme polie'],
                'examples': 'Bonjour tout le monde (Hello everyone)',
                'examples_list': [('Bonjour tout le monde', 'Hello everyone')],
            },
            'salut': {
                'word': 'Salut',
                'type': 'noun',
                'definitions': 'Informel',
                'definitions_list': ['Informel'],
                'examples': 'Salut ! (Hi!)',
                'examples_list': [('Salut !', 'Hi!')],
            },
        }
        builder.exported_words = set()
        builder.exported_deck_version = None
        builder.save_exported_words = lambda: None

        with tempfile.TemporaryDirectory() as tmp:
            builder.exported_words_file = os.path.join(tmp, 'exported_words.json')
            builder.export_to_anki('Test Deck', include_exported_words=True, selected_words={'salut'})

        deck = self.package_cls.last_deck
        self.assertEqual(len(deck.notes), 1)
        self.assertEqual(deck.notes[0].fields[0], 'Salut')
        self.assertIn('salut', builder.exported_words)

    def test_export_strips_brace_artifacts(self):
        builder = object.__new__(VocabBuilder)
        builder.ui = _StubUI()
        builder.console = types.SimpleNamespace()
        builder.word_entries = {
            'bedrohen': {
                'word': 'Bedrohen',
                'type': 'verb',
                'definitions': 'to threaten; to imperil; }',
                'definitions_list': [
                    'to threaten, menace',
                    'to imperil',
                    '}',
                ],
                'examples': 'Der Klimawandel bedroht die Zukunft kleiner Inselstaaten. (Climate change threatens the future of small island nations.); }',
                'examples_list': [
                    ('Der Klimawandel bedroht die Zukunft kleiner Inselstaaten.', 'Climate change threatens the future of small island nations.'),
                    ('}', ''),
                ],
            }
        }
        builder.exported_words = set()
        builder.exported_deck_version = None
        builder.save_exported_words = lambda: None

        with tempfile.TemporaryDirectory() as tmp:
            builder.exported_words_file = os.path.join(tmp, 'exported_words.json')
            builder.export_to_anki('Test Deck')

        deck = self.package_cls.last_deck
        self.assertEqual(deck.notes[0].fields[0], 'Bedrohen')
        self.assertNotIn('}', deck.notes[0].fields[2])
        self.assertNotIn('}', deck.notes[0].fields[3])
    def test_export_to_anki_can_include_already_exported_words(self):
        builder = object.__new__(VocabBuilder)
        builder.ui = _StubUI()
        builder.console = types.SimpleNamespace()
        builder.word_entries = {
            'bonjour': {
                'word': 'Bonjour',
                'type': 'noun',
                'definitions': 'Salut amical; Forme polie',
                'definitions_list': ['Salut amical', 'Forme polie'],
                'examples': 'Bonjour tout le monde (Hello everyone)',
                'examples_list': [('Bonjour tout le monde', 'Hello everyone')],
            },
            'salut': {
                'word': 'Salut',
                'type': 'noun',
                'definitions': 'Informel',
                'definitions_list': ['Informel'],
                'examples': 'Salut ! (Hi!)',
                'examples_list': [('Salut !', 'Hi!')],
            },
        }
        builder.exported_words = {'bonjour', 'salut'}
        builder.exported_deck_version = None
        builder.save_exported_words = lambda: None

        with tempfile.TemporaryDirectory() as tmp:
            builder.exported_words_file = os.path.join(tmp, 'exported_words.json')
            builder.export_to_anki('Test Deck', include_exported_words=True)

        package = self.package_cls
        deck = package.last_deck
        self.assertEqual(len(deck.notes), 2)
        exported_fields = {tuple(note.fields) for note in deck.notes}
        self.assertIn(
            ('Bonjour', 'noun', '<ul class="entry-list"><li>Salut amical</li><li>Forme polie</li></ul>', '<ul class="entry-list"><li>Bonjour tout le monde (Hello everyone)</li></ul>'),
            exported_fields,
        )
        self.assertIn(
            ('Salut', 'noun', '<ul class="entry-list"><li>Informel</li></ul>', '<ul class="entry-list"><li>Salut ! (Hi!)</li></ul>'),
            exported_fields,
        )
        self.assertEqual(builder.exported_deck_version, FRENCH_CONFIG.anki.version_id)

    def test_export_auto_rebuilds_when_template_version_changes(self):
        builder = object.__new__(VocabBuilder)
        builder.ui = _StubUI()
        builder.console = types.SimpleNamespace()
        builder.word_entries = {
            'bonjour': {
                'word': 'Bonjour',
                'type': 'noun',
                'definitions': 'Salut amical; Forme polie',
                'definitions_list': ['Salut amical', 'Forme polie'],
                'examples': 'Bonjour tout le monde (Hello everyone)',
                'examples_list': [('Bonjour tout le monde', 'Hello everyone')],
            },
            'salut': {
                'word': 'Salut',
                'type': 'noun',
                'definitions': 'Informel',
                'definitions_list': ['Informel'],
                'examples': 'Salut ! (Hi!)',
                'examples_list': [('Salut !', 'Hi!')],
            },
        }
        builder.exported_words = {'bonjour', 'salut'}
        builder.exported_deck_version = "legacy-version"
        builder.save_exported_words = lambda: None

        with tempfile.TemporaryDirectory() as tmp:
            builder.exported_words_file = os.path.join(tmp, 'exported_words.json')
            builder.export_to_anki('Test Deck')

        deck = self.package_cls.last_deck
        self.assertEqual(deck.name, 'Test Deck')
        self.assertEqual(len(deck.notes), 2)
        self.assertEqual(builder.exported_deck_version, FRENCH_CONFIG.anki.version_id)

    def test_export_records_metadata_and_honors_output_path(self):
        builder = object.__new__(VocabBuilder)
        builder.ui = _StubUI()
        builder.console = types.SimpleNamespace()
        builder.word_entries = {
            'bonjour': {
                'word': 'Bonjour',
                'type': 'noun',
                'definitions': 'Salut amical',
                'definitions_list': ['Salut amical'],
                'examples': 'Bonjour ! (Hello!)',
                'examples_list': [('Bonjour !', 'Hello!')],
            },
        }
        builder.exported_words = set()
        builder.exported_deck_version = None
        builder.save_exported_words = lambda: None

        with tempfile.TemporaryDirectory() as tmp:
            builder.exported_words_file = os.path.join(tmp, 'exported_words.json')
            explicit_destination = Path(tmp) / "anki_exports" / "Deck Name.apkg"
            builder.export_to_anki(
                "Deck Name.apkg",
                output_path=explicit_destination,
                export_context="selected",
            )
            expected_path = explicit_destination.resolve()

        package = self.package_cls
        self.assertEqual(Path(package.last_written_path), expected_path)
        deck = package.last_deck
        self.assertEqual(deck.name, 'Deck Name')

        metadata = builder.last_export_metadata
        self.assertIsInstance(metadata, dict)
        self.assertEqual(metadata["deck_name"], "Deck Name")
        self.assertEqual(Path(metadata["path"]), expected_path)
        self.assertEqual(metadata["path_source"], "explicit")
        self.assertEqual(metadata["export_context"], "selected")
        self.assertIn('total_words', metadata)
        self.assertIn('new_words', metadata)


if __name__ == '__main__':
    unittest.main()
