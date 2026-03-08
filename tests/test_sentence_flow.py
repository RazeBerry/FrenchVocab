import os
import tempfile
import unittest

from vocab_builder.core import VocabBuilder
from vocab_builder.core import session_ui as session_ui_module


class _FakeLLMClient:
    def __init__(self):
        self.last_prompt = None
        self._response = (
            "Spelling Check: OK\n"
            "Correctly Spelt Word: input\n"
            "Word Type: sentence\n"
            "Definitions:\n"
            "a. translation\n"
            "b. note\n"
            "c. paraphrase\n"
            "Examples:\n"
            "1. FR1\n( EN1 )\n"
            "2. FR2\n( EN2 )\n"
            "3. FR3\n( EN3 )\n"
        )

    def stream(self, prompt: str):
        self.last_prompt = prompt
        # yield the whole response once
        yield self._response

    def model_label(self):
        return "Fake Gemini"


class TestSentenceFlow(unittest.TestCase):
    def setUp(self):
        os.environ['GEMINI_API_KEY'] = 'AIza' + 'x'*36

    def _builder(self, client=None, tex_path=None):
        if tex_path is None:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.tex') as tf:
                tex_path = tf.name
        return VocabBuilder(tex_path, provider='gemini', verbose=False, client=client)

    def test_detect_input_type_sentence(self):
        b = self._builder(client=_FakeLLMClient())
        self.assertEqual(b.detect_input_type("short"), 'word')
        self.assertEqual(b.detect_input_type("deux mots"), 'expression')
        self.assertEqual(b.detect_input_type("ligne 1\nligne 2"), 'sentence')
        self.assertEqual(b.detect_input_type("Ceci est une phrase."), 'sentence')

    def test_query_ai_includes_detected_type(self):
        fake = _FakeLLMClient()
        b = self._builder(client=fake)
        _ = b.query_ai("Ligne 1\nLigne 2")
        self.assertIn("Detected Input Type: sentence", fake.last_prompt or "")

    def test_get_word_input_single_line(self):
        b = self._builder(client=_FakeLLMClient())
        # Patch builtins.input to simulate single line input - Enter submits immediately
        orig_input = __builtins__['input']
        try:
            __builtins__['input'] = lambda prompt='': "bonjour"
            out = b.get_word_input()
        finally:
            __builtins__['input'] = orig_input
        self.assertEqual(out, "bonjour")

    def test_get_word_input_escape_cancels(self):
        b = self._builder(client=_FakeLLMClient())
        import vocab_builder.core.vocab as vocab_module
        original_read_line = vocab_module.read_line
        try:
            vocab_module.read_line = lambda prompt="": "\x1b"
            result = b.get_word_input()
        finally:
            vocab_module.read_line = original_read_line
        self.assertEqual(result, "")

    def test_check_spelling_records_suggestion(self):
        b = self._builder(client=_FakeLLMClient())
        ai_resp = (
            "Spelling Check: typo\n"
            "Correctly Spelt Word: correction\n"
            "Word Type: noun\n"
            "Definitions:\n"
            "a. d1\n"
            "Examples:\n"
            "1. fr\n(en)\n"
            "2. fr\n(en)\n"
            "3. fr\n(en)\n"
        )
        # Mock ui.confirm to accept the correction
        b.ui.confirm = lambda *args, **kwargs: True
        res = b.check_spelling("orig", ai_resp)
        # Now returns corrected word immediately (user confirmed)
        self.assertEqual(res, "correction")

    def test_check_spelling_returns_input_when_no_change(self):
        b = self._builder(client=_FakeLLMClient())
        ai_resp = (
            "Spelling Check: OK\n"
            "Correctly Spelt Word: orig\n"
            "Word Type: noun\n"
            "Definitions:\n"
            "a. d1\n"
            "Examples:\n"
            "1. fr\n(en)\n"
        )
        res = b.check_spelling("orig", ai_resp)
        self.assertEqual(res, "orig")
        # No longer using pending_spelling_suggestion - decision made immediately

    def test_check_spelling_ignores_trailing_punctuation(self):
        b = self._builder(client=_FakeLLMClient())
        ai_resp = (
            "Spelling Check: punctuation\n"
            "Correctly Spelt Word: exploit d'huissier\n"
            "Word Type: expression\n"
        )
        res = b.check_spelling("exploit d'huissier,", ai_resp)
        self.assertEqual(res, "exploit d'huissier")
        # Trailing punctuation normalized - no user confirmation needed

    def test_format_latex_entry_preserves_sentence_casing(self):
        latex = VocabBuilder.format_latex_entry(
            "“Mais le devoir…”,", "sentence", ["t"], [("fr", "en")]
        )
        # Word appears exactly (escaped for LaTeX may not change curly quotes)
        self.assertIn("\\entry{“Mais le devoir…”,}{sentence}", latex)

    def test_routing_sentences_calls_translator(self):
        # Force routing
        fake_client = _FakeLLMClient()
        b = self._builder(client=fake_client)
        b.route_sentences = True

        # Stub translator with a spy
        calls = {'n': 0}
        class _Spy:
            entry_count = 0
            def translate_and_save(self, text, provided_translation=None):
                calls['n'] += 1
                return True
        b.fr_to_eng_translator = _Spy()
        # Stub interactive_menu to return "menu" (go back to main menu)
        b.ui.interactive_menu = lambda *args, **kwargs: "menu"

        # Make get_word_input return a sentence
        b.get_word_input = lambda: "Ceci est une phrase."

        # Confirm.ask default True via stubs; run handler
        b.handle_new_word_entry()
        self.assertEqual(calls['n'], 1)

    def test_routed_sentence_does_not_show_vocab_quick_actions(self):
        fake_client = _FakeLLMClient()
        b = self._builder(client=fake_client)
        b.route_sentences = True

        class _Spy:
            entry_count = 0

            def translate_and_save(self, text, provided_translation=None):
                return True

        b.fr_to_eng_translator = _Spy()
        b.get_word_input = lambda: "Ceci est une phrase."
        b.ui.interactive_menu = lambda *args, **kwargs: "menu"
        b._show_word_entry_quick_actions = lambda: (_ for _ in ()).throw(
            AssertionError("vocabulary quick actions should not open after sentence routing")
        )

        b.handle_new_word_entry()

    def test_failed_sentence_routing_falls_back_to_vocab_flow(self):
        fake_client = _FakeLLMClient()
        b = self._builder(client=fake_client)
        b.route_sentences = True
        b.sentence_examples_in_vocab = False

        class _Spy:
            entry_count = 0

            def translate_and_save(self, text, provided_translation=None):
                return False

        b.fr_to_eng_translator = _Spy()
        b.query_ai = lambda _text: "stub"
        b.parse_ai_response = lambda _resp: (
            ["sentence"],
            ["translated sentence"],
            [("FR ex", "EN ex")],
        )
        b.check_duplicate = lambda _word: None
        b.is_valid_latex_entry = lambda _entry: True
        b.display_parsed_info = lambda *args, **kwargs: None
        b.display_latex_entry = lambda *args, **kwargs: None
        b.ui.confirm = lambda *args, **kwargs: True
        b.ui.interactive_menu = lambda *args, **kwargs: "menu"

        captured = {}

        def _capture_insert(entry, word):
            captured["entry"] = entry

        b.insert_entry_alphabetically = _capture_insert
        b.get_word_input = lambda: "Ceci est une phrase."

        b.handle_new_word_entry()

        self.assertIn("\\entry{Ceci est une phrase.}{sentence}", captured.get("entry", ""))

    def test_post_translation_menu_returns_add_without_recursing(self):
        calls = {"add": 0}

        class _App:
            auto_translator = None
            eng_to_fr_translator = None
            fr_to_eng_translator = None

            class _UI:
                @staticmethod
                def interactive_menu(*_args, **_kwargs):
                    return "add"

            ui = _UI()

            @staticmethod
            def handle_new_word_entry():
                calls["add"] += 1

        action = session_ui_module.show_post_translation_menu(_App())

        self.assertEqual(action, "add")
        self.assertEqual(calls["add"], 0)

    def test_sentence_examples_omitted_when_not_routing(self):
        # Disable routing, ensure examples removed for sentences
        fake_client = _FakeLLMClient()
        b = self._builder(client=fake_client)
        b.route_sentences = False
        b.sentence_examples_in_vocab = False

        # Stub AI + parser
        b.query_ai = lambda x: "stub"
        b.parse_ai_response = lambda _resp: (['sentence'], ['EN translation', 'note', 'paraphrase'], [('FR ex', 'EN ex')])
        b.check_duplicate = lambda _w: None
        b.is_valid_latex_entry = lambda _s: True

        captured = {}
        def _capture_insert(entry, word):
            captured['entry'] = entry
        b.insert_entry_alphabetically = _capture_insert
        b.ui.interactive_menu = lambda *args, **kwargs: "menu"  # Return to menu after save

        b.get_word_input = lambda: "Phrase terminée."
        b.handle_new_word_entry()

        # Ensure no \item lines under the examples block
        self.assertIn("\\entry{Phrase terminée.}{sentence}", captured.get('entry', ''))
        # Should not contain example \item content since examples were dropped
        self.assertNotIn("FR ex \\\\ (EN ex)", captured.get('entry', ''))

    def test_decline_preview_confirmation_skips_save(self):
        fake_client = _FakeLLMClient()
        b = self._builder(client=fake_client)

        b.get_word_input = lambda: "nein"
        b.query_ai = lambda _word: "stubbed"
        b.check_spelling = lambda word, _resp: word
        b.parse_ai_response = lambda _resp: (
            ['verb'],
            ['to refuse politely'],
            [('FR sample', 'EN sample')],
        )
        b.check_duplicate = lambda _w: None
        b.is_valid_latex_entry = lambda _entry: True
        b.display_parsed_info = lambda *args, **kwargs: None
        b.display_latex_entry = lambda *args, **kwargs: None

        b.ui.confirm = lambda *args, **kwargs: False

        insert_called = {'value': False}
        def _record_insert(_entry, _word):
            insert_called['value'] = True
        b.insert_entry_alphabetically = _record_insert

        added_count = {'value': 0}
        def _record_add(*args, **kwargs):
            added_count['value'] += 1
        b.add_word_to_entries = _record_add

        def _fail_alphabetize():
            raise AssertionError("alphabetize_entries should not run when confirmation is declined")
        b.alphabetize_entries = _fail_alphabetize

        b.handle_new_word_entry()

        self.assertFalse(insert_called['value'])
        self.assertEqual(added_count['value'], 0)

    def test_failed_insert_does_not_update_memory_or_show_success(self):
        fake_client = _FakeLLMClient()
        b = self._builder(client=fake_client)

        b.get_word_input = lambda: "bonjour"
        b.query_ai = lambda _word: "stubbed"
        b.check_spelling = lambda word, _resp: word
        b.parse_ai_response = lambda _resp: (
            ['noun'],
            ['hello'],
            [('FR sample', 'EN sample')],
        )
        b.check_duplicate = lambda _w: None
        b.is_valid_latex_entry = lambda _entry: True
        b.display_parsed_info = lambda *args, **kwargs: None
        b.display_latex_entry = lambda *args, **kwargs: None
        b.ui.confirm = lambda *args, **kwargs: True
        b.insert_entry_alphabetically = lambda *_args, **_kwargs: False

        added_count = {'value': 0}
        b.add_word_to_entries = lambda *args, **kwargs: added_count.__setitem__('value', added_count['value'] + 1)

        success_messages = []
        b.ui.success = lambda message, *args, **kwargs: success_messages.append(message)
        b._show_word_entry_quick_actions = lambda: (_ for _ in ()).throw(
            AssertionError("quick actions should not open when saving fails")
        )

        b.handle_new_word_entry()

        self.assertEqual(added_count['value'], 0)
        self.assertFalse(any("Entry saved successfully!" in msg for msg in success_messages))

    def test_failed_duplicate_merge_does_not_continue_as_success(self):
        fake_client = _FakeLLMClient()
        b = self._builder(client=fake_client)

        b.get_word_input = lambda: "bonjour"
        b.query_ai = lambda _word: "stubbed"
        b.check_spelling = lambda word, _resp: word
        b.parse_ai_response = lambda _resp: (
            ['noun'],
            ['hello'],
            [('FR sample', 'EN sample')],
        )
        b.check_duplicate = lambda _w: "bonjour"
        b.is_valid_latex_entry = lambda _entry: True
        b.display_parsed_info = lambda *args, **kwargs: None
        b.display_latex_entry = lambda *args, **kwargs: None
        b.ui.interactive_menu = lambda *args, **kwargs: "merge"
        b._vocab_repo.merge_into_existing = lambda *_args, **_kwargs: False
        b._show_word_entry_quick_actions = lambda: (_ for _ in ()).throw(
            AssertionError("quick actions should not open after a failed merge")
        )

        b.handle_new_word_entry()

    def test_revert_to_original_spelling_still_saves(self):
        fake_client = _FakeLLMClient()
        b = self._builder(client=fake_client)

        ai_resp = (
            "Spelling Check: typo\n"
            "Correctly Spelt Word: correction\n"
            "Word Type: verb\n"
            "Definitions:\n"
            "a. def1\n"
            "Examples:\n"
            "1. fr\n(en)\n"
        )

        b.get_word_input = lambda: "orig"
        b.query_ai = lambda _word: ai_resp
        b.parse_ai_response = lambda _resp: (
            ['verb'],
            ['meaning'],
            [('FR sample', 'EN sample')],
        )
        b.check_duplicate = lambda _w: None
        b.is_valid_latex_entry = lambda _entry: True
        b.display_parsed_info = lambda *args, **kwargs: None

        displayed_entries = []
        b.display_latex_entry = lambda entry: displayed_entries.append(entry)

        def _confirm(message, *args, **kwargs):
            if "Use corrected spelling" in message:
                return False
            if "Add this entry" in message:
                return True
            return True
        b.ui.confirm = _confirm

        inserted = {}
        def _record_insert(entry, word):
            inserted['entry'] = entry
            inserted['word'] = word
        b.insert_entry_alphabetically = _record_insert

        added_words = []
        b.add_word_to_entries = lambda word, *_args: added_words.append(word)
        b.alphabetize_entries = lambda *args, **kwargs: None
        b.ui.interactive_menu = lambda *args, **kwargs: "menu"  # Return to menu after save

        b.handle_new_word_entry()

        # With new flow, user declines correction immediately, so only ONE entry displayed (with original spelling)
        self.assertGreaterEqual(len(displayed_entries), 1)
        self.assertIn("\\entry{Orig}{verb}", displayed_entries[-1])
        self.assertEqual(inserted.get('word'), "orig")
        self.assertEqual(added_words, ["orig"])


if __name__ == '__main__':
    unittest.main()
