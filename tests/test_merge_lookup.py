"""A merge look-up in the terminal asks only for what the held entry lacks."""

from unittest.mock import MagicMock

from vocab_builder.ai_prompts import AI_PROMPT_TEMPLATE, vocabulary_prompt
from vocab_builder.core import VocabBuilder
from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.languages import get_language_config

NOTHING_MISSING = (
    "Spelling Check: OK\nCorrectly Spelt Word: agaçante\nWord Type: adjective\n"
    "Definitions:\nExamples:\n"
)


class _Client:
    def stream(self, prompt, **_kwargs):
        yield NOTHING_MISSING

    def model_label(self):
        return "Test provider"


def _builder(tmp_path, monkeypatch, typed):
    monkeypatch.setenv("VOCABBUILDER_FORCE_SYNC_LOAD", "1")
    monkeypatch.setenv("VOCABBUILDER_HISTORY_DIR", str(tmp_path / "history"))
    tex = tmp_path / "FrenchVocab.tex"
    VocabRepository(
        latex_file=tex, entry_command="\\entry", language_config=get_language_config("fr"), ui=MagicMock()
    ).create_initial_tex_file()  # holds the template's "agaçante"
    builder = VocabBuilder(str(tex), provider="gemini", verbose=False, client=_Client())
    calls = []

    def query_ai(word, held=None):
        calls.append((word, held))
        return NOTHING_MISSING

    infos = []
    builder.query_ai = query_ai
    builder.get_word_input = lambda: typed
    builder.check_spelling = lambda _word, _response: "agaçante"
    builder.ui.interactive_menu = lambda *_args, **_kwargs: "merge"
    builder.ui.info = lambda message, *_args, **_kwargs: infos.append(message)
    builder.insert_entry_alphabetically = MagicMock(side_effect=AssertionError("nothing may be written"))
    return builder, calls, infos


def test_a_chosen_merge_sends_the_held_entry_and_an_empty_answer_writes_nothing(tmp_path, monkeypatch):
    builder, calls, infos = _builder(tmp_path, monkeypatch, "agacante")

    builder.handle_new_word_entry()

    ((word, held),) = calls
    assert word == "agacante"
    assert held["definitions_list"][0] == "Annoying, irritating"
    assert any("Nothing new" in message for message in infos)


def test_a_correction_that_finds_a_held_word_asks_again_with_the_held_entry(tmp_path, monkeypatch):
    builder, calls, infos = _builder(tmp_path, monkeypatch, "agasante")

    builder.handle_new_word_entry()

    assert [word for word, _held in calls] == ["agasante", "agaçante"]
    assert calls[0][1] is None
    assert calls[1][1]["definitions_list"][0] == "Annoying, irritating"
    assert any("Nothing new" in message for message in infos)


def test_the_held_senses_reach_the_prompt():
    prompt = vocabulary_prompt(
        AI_PROMPT_TEMPLATE,
        "ronger",
        "word",
        {"type": "verb", "definitions_list": ["To gnaw {x}.", "To erode."]},
    )

    assert "Part of speech: verb\n- To gnaw {x}.\n- To erode." in prompt
    assert prompt.index("Input: \"ronger\"") < prompt.index("Held entry:")
