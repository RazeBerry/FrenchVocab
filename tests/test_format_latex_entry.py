import sys
import types
import unittest


# ---- Minimal stubs to allow importing FrenchVocab without external deps ----

# Stub for genanki to bypass optional dependency during import time
genanki_stub = types.ModuleType('genanki')

class _Dummy:
    def __init__(self, *args, **kwargs):
        pass

class _DummyPackage:
    def __init__(self, deck):
        self.deck = deck
    def write_to_file(self, *_args, **_kwargs):
        pass

genanki_stub.Model = _Dummy
genanki_stub.Deck = _Dummy
genanki_stub.Note = _Dummy
genanki_stub.Package = _DummyPackage
sys.modules['genanki'] = genanki_stub

# Stub for llm_client to avoid importing google SDKs
llm_client_stub = types.ModuleType('llm_client')

class _LLMClient:
    def stream(self, _prompt: str):
        yield ""

class _GeminiClient(_LLMClient):
    pass

class _ProviderFactory:
    @staticmethod
    def create(_provider_name: str, _api_key: str = None):
        return _GeminiClient()
    @staticmethod
    def default_provider() -> str:
        return 'gemini'

llm_client_stub.LLMClient = _LLMClient
llm_client_stub.GeminiClient = _GeminiClient
llm_client_stub.ProviderFactory = _ProviderFactory
sys.modules['llm_client'] = llm_client_stub


# Now we can import the module under test
import types as _types

# Stub for rich.* modules
rich_console = _types.ModuleType('rich.console')
class _Console:
    def print(self, *args, **kwargs):
        pass
    def status(self, *_args, **_kwargs):
        class _Ctx:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
        return _Ctx()
    def input(self, *args, **kwargs):
        return ""
rich_console.Console = _Console
sys.modules['rich.console'] = rich_console

rich_progress = _types.ModuleType('rich.progress')
class _Progress:
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False
    def add_task(self, *_args, **_kwargs): return 1
    def advance(self, *_args, **_kwargs): pass
    def update(self, *_args, **_kwargs): pass
rich_progress.Progress = _Progress
sys.modules['rich.progress'] = rich_progress

rich_prompt = _types.ModuleType('rich.prompt')
class _Prompt:
    @staticmethod
    def ask(_msg, choices=None, default=None):
        return default or (choices[0] if choices else "")
class _Confirm:
    @staticmethod
    def ask(_msg, default=False):
        return default
rich_prompt.Prompt = _Prompt
rich_prompt.Confirm = _Confirm
sys.modules['rich.prompt'] = rich_prompt

rich_table = _types.ModuleType('rich.table')
class _Table:
    def __init__(self, *args, **kwargs): pass
    def add_column(self, *args, **kwargs): pass
    def add_row(self, *args, **kwargs): pass
rich_table.Table = _Table
sys.modules['rich.table'] = rich_table

rich_panel = _types.ModuleType('rich.panel')
class _Panel:
    def __init__(self, *args, **kwargs): pass
rich_panel.Panel = _Panel
sys.modules['rich.panel'] = rich_panel

rich_text = _types.ModuleType('rich.text')
class _Text: pass
rich_text.Text = _Text
sys.modules['rich.text'] = rich_text

# Stub keyring
keyring_stub = _types.ModuleType('keyring')
class _KeyringErrors(_types.SimpleNamespace):
    class KeyringError(Exception):
        pass
sys.modules['keyring'] = keyring_stub
sys.modules['keyring.errors'] = _types.ModuleType('keyring.errors')
setattr(sys.modules['keyring.errors'], 'KeyringError', _KeyringErrors.KeyringError)

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
