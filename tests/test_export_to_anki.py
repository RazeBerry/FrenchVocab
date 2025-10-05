import os
import sys
import tempfile
import types
import unittest

sys.path.append(os.path.dirname(__file__))
from _stubs import install_basic_stubs
install_basic_stubs()

import FrenchVocab
import genanki


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
        builder = object.__new__(FrenchVocab.FrenchVocabBuilder)
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
        self.assertEqual(note.fields[2], '• Salut amical<br>• Forme polie')
        self.assertEqual(note.fields[3], '• Bonjour tout le monde (Hello everyone)')

        self.assertIn('bonjour', builder.exported_words)
        self.assertIn('salut', builder.exported_words)


if __name__ == '__main__':
    unittest.main()
