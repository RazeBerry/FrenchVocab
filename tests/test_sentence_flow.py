import os
import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace

# Ensure stubs are installed for rich and keyring, etc.
import sys
sys.path.append(str(Path(__file__).parent))
from _stubs import install_basic_stubs
install_basic_stubs()

import FrenchVocab


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
        os.environ['GEMINI_API_KEY'] = 'x'*40

    def _builder(self, client=None, tex_path=None):
        if tex_path is None:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.tex') as tf:
                tex_path = tf.name
        return FrenchVocab.FrenchVocabBuilder(tex_path, provider='gemini', verbose=False, client=client)

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

    def test_get_word_input_multiline(self):
        b = self._builder(client=_FakeLLMClient())
        # Patch builtins.input to simulate multiline input followed by empty line
        seq = iter(["Première ligne", "Deuxième ligne", ""])  # empty line to submit
        orig_input = __builtins__['input']
        try:
            __builtins__['input'] = lambda prompt='': next(seq)
            out = b.get_word_input()
        finally:
            __builtins__['input'] = orig_input
        self.assertEqual(out, "Première ligne\nDeuxième ligne")

    def test_check_spelling_cancel_on_n(self):
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
        # Provide 'n' to cancel
        seq = iter(["n"])  # reject correction
        orig_input = __builtins__['input']
        try:
            __builtins__['input'] = lambda prompt='': next(seq)
            res = b.check_spelling("orig", ai_resp)
        finally:
            __builtins__['input'] = orig_input
        self.assertIsNone(res)

    def test_format_latex_entry_preserves_sentence_casing(self):
        latex = FrenchVocab.FrenchVocabBuilder.format_latex_entry(
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
            def translate_and_save(self, text):
                calls['n'] += 1
                return True
        b.fr_to_eng_translator = _Spy()

        # Make get_word_input return a sentence
        b.get_word_input = lambda: "Ceci est une phrase."

        # Confirm.ask default True via stubs; run handler
        b.handle_new_word_entry()
        self.assertEqual(calls['n'], 1)

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

        b.get_word_input = lambda: "Phrase terminée."
        b.handle_new_word_entry()

        # Ensure no \item lines under the examples block
        self.assertIn("\\entry{Phrase terminée.}{sentence}", captured.get('entry', ''))
        # Should not contain example \item content since examples were dropped
        self.assertNotIn("FR ex \\\\ (EN ex)", captured.get('entry', ''))


if __name__ == '__main__':
    unittest.main()
