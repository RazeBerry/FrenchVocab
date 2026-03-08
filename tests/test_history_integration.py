from pathlib import Path

from vocab_builder.core import VocabBuilder


class _StubClient:
    def stream(self, prompt: str):
        yield "stub"

    def model_label(self):
        return "Stub Model"


def test_handle_new_word_entry_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_HISTORY_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)

    tex_path = tmp_path / "FrenchVocab.tex"
    builder = VocabBuilder(str(tex_path), provider="gemini", verbose=False, client=_StubClient())

    builder.get_word_input = lambda: "bonjour"
    builder.query_ai = lambda _: "stub"
    builder.parse_ai_response = lambda _resp: (["noun"], ["greeting"], [("Bonjour", "Hello")])
    builder.check_duplicate = lambda _w: None
    builder.is_valid_latex_entry = lambda _entry: True
    builder.display_parsed_info = lambda *args, **kwargs: None
    builder.display_latex_entry = lambda *args, **kwargs: None
    builder.ui.confirm = lambda *args, **kwargs: True
    builder.ui.interactive_menu = lambda *args, **kwargs: "menu"  # Return to menu, don't recurse
    builder.alphabetize_entries = lambda *args, **kwargs: None

    builder.handle_new_word_entry()

    history_path = Path(tmp_path) / "fr_translations.jsonl"
    assert history_path.exists()
    contents = history_path.read_text(encoding="utf-8").strip()
    assert '"word": "bonjour"' in contents
    assert '"flow": "vocab"' in contents
