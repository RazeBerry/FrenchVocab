from types import SimpleNamespace

from vocab_builder.ai_response_parser import parse_ai_response_text
from vocab_builder.anki_exporter import (
    AnkiExportEntry,
    AnkiExporter,
    AnkiMistakeDeckExporter,
)
from vocab_builder.core import VocabBuilder
from vocab_builder.core.llm_coordinator import InitState
from vocab_builder.core.session_ui import show_main_menu, show_translation_menu
from vocab_builder.languages import get_language_config


class _FakeClient:
    def stream(self, _prompt):
        yield ""

    def model_label(self):
        return "Fake provider"


class _CaptureUI:
    def __init__(self):
        self.menu_options = []
        self.panels = []
        self.warnings = []

    def panel(self, content, **kwargs):
        self.panels.append((content, kwargs))

    def interactive_menu(self, _title, options, *_args, **_kwargs):
        self.menu_options.append(options)
        return "exit"

    def warning(self, message, *_args, **_kwargs):
        self.warnings.append(message)


class _ReadyLLM:
    init_state = InitState.READY

    def await_init(self, timeout=None):  # noqa: ARG002
        return True


def test_english_builder_omits_bilingual_files_and_translators(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCABBUILDER_HISTORY_DIR", str(tmp_path / "history"))
    builder = VocabBuilder(
        str(tmp_path / "EnglishVocab.tex"),
        provider="gemini",
        client=_FakeClient(),
        language="en",
    )

    assert builder.language_code == "en"
    assert builder.eng_to_target_latex_file is None
    assert builder.target_to_eng_latex_file is None
    assert builder.eng_to_target_translator is None
    assert builder.target_to_eng_translator is None
    assert builder.auto_translator is None
    assert builder.exported_words_file == tmp_path / "exported_words_en.json"
    workflow = builder._build_word_entry_workflow()
    assert workflow._on_entry_saved == builder._anki.register_entry_order


def test_english_main_menu_hides_translation_tools():
    ui = _CaptureUI()
    config = get_language_config("en")
    app = SimpleNamespace(
        eng_to_target_translator=None,
        target_to_eng_translator=None,
        eng_to_target_latex_file=None,
        target_to_eng_latex_file=None,
        language_config=config,
        entry_count=4,
        _llm=_ReadyLLM(),
        ui=ui,
        _ui_text=lambda key, fallback: config.ui_strings.get(key, fallback),
        enable_composition=False,
    )

    assert show_main_menu(app) == "exit"

    keys = [key for key, _label in ui.menu_options[0]]
    assert "add" in keys
    assert "translate" not in keys
    assert "Translations:" not in ui.panels[0][0]

    assert show_translation_menu(app) == "back"
    assert any("monolingual" in warning.lower() for warning in ui.warnings)


def test_english_prompt_response_reuses_existing_parser_shape():
    response = """
Spelling Check: OK
Correctly Spelt Word:
recondite
Word Type:
adjective
Definitions:
a. Difficult for most people to understand; obscure.
b. Formal and uncommon, often describing specialized knowledge or writing.
c. Commonly modifies subjects, arguments, discussions, or explanations.
Examples:
1. The monograph assumes a recondite knowledge of medieval law.
(The monograph assumes obscure specialist knowledge of medieval law.)
2. She made the recondite argument accessible to newcomers.
(She made the difficult, highly specialized argument accessible to newcomers.)
3. Their conversation drifted into recondite questions of textual criticism.
(Their conversation moved into obscure questions about analyzing texts.)
""".strip()

    parsed = parse_ai_response_text(response)

    assert parsed.word_type == ["adjective"]
    assert len(parsed.definitions) == 3
    assert parsed.examples[0] == (
        "The monograph assumes a recondite knowledge of medieval law.",
        "The monograph assumes obscure specialist knowledge of medieval law.",
    )
    assert parsed.parsing_warnings == []


def test_english_anki_uses_dedicated_fields_and_stable_ids():
    config = get_language_config("en")
    entry = AnkiExportEntry(
        word="Recondite",
        word_type="adjective",
        definitions=["Difficult to understand; obscure."],
        examples=[
            (
                "The paper is recondite.",
                "The paper is obscure and difficult.",
            )
        ],
        order=17,
    )

    first = AnkiExporter(config.anki.default_deck_name, config.anki)
    second = AnkiExporter(config.anki.default_deck_name, config.anki)
    first_deck = first.build_deck([entry])

    assert first.deck_id == second.deck_id
    assert first.model_id == second.model_id
    assert first_deck.notes[0].due == 17
    assert first_deck.notes[0].sort_field == "Recondite"
    assert first_deck.notes[0].fields == [
        "Recondite",
        "adjective",
        '<ul class="entry-list"><li>Difficult to understand; obscure.</li></ul>',
        (
            '<ul class="entry-list"><li>The paper is recondite. '
            "(The paper is obscure and difficult.)</li></ul>"
        ),
    ]

    mistake_exporter = AnkiMistakeDeckExporter(config.anki)
    assert mistake_exporter.deck_name == "EnglishDeck::Mistakes"
