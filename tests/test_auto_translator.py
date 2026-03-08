from vocab_builder.languages.base import (
    LanguageConfig,
    TranslatorConfig,
    VocabTemplate,
    AnkiConfig,
    AnkiCardTemplate,
)
from vocab_builder.core.auto_translator import AutoTranslator
from rich.console import Console


class _FakeLLMClient:
    def __init__(self, response_text: str):
        self.response_text = response_text

    def stream(self, _prompt: str, *, thinking_level: str = "low"):
        response_text = self.response_text

        def _generator():
            yield response_text
            return {"usage": {"output_tokens": 12}}

        return _generator()


class _SpyTranslator:
    def __init__(self):
        self.calls = []
        self.entry_count = 0

    def translate_and_save(self, source_text, provided_translation=None):
        self.calls.append((source_text, provided_translation))
        return True


def _language_config(prompt_text: str) -> LanguageConfig:
    translator_cfg = TranslatorConfig(
        default_filename="dummy.tex",
        initial_tex_content="",
        final_tex_content="",
        prompt_template="",
        prompt_variable="text",
        source_label="English",
        target_label="French",
        ui_title="Dummy",
        table_headers=("Source", "Target"),
        latex_commands=("cmd",),
    )
    vocab_template = VocabTemplate(initial_content="", sample_entry="", final_content="")
    anki_cfg = AnkiConfig(
        deck_namespace="ns",
        default_deck_name="Deck",
        model_seed="seed",
        model_name="Model",
        field_names=("Front", "Back"),
        card_templates=(AnkiCardTemplate(name="Card1", question_format="", answer_format=""),),
        card_css="",
    )
    return LanguageConfig(
        code="fr",
        display_name="French",
        prompt_template="",
        vocab_filename="vocab.tex",
        eng_to_target_filename="eng.tex",
        target_to_eng_filename="fr.tex",
        latex_babel_languages=("french", "english"),
        ui_strings={},
        input_validator=lambda text, allow: True,
        eng_to_target=translator_cfg,
        target_to_eng=translator_cfg,
        vocab=vocab_template,
        anki=anki_cfg,
        aliases=(),
        auto_prompt_template=prompt_text,
        auto_prompt_variable="source_text",
        auto_direction_tokens=("english_to_french", "french_to_english"),
    )


def test_auto_translator_routes_to_english_direction(monkeypatch):
    prompt = "Input:\n{source_text}"
    config = _language_config(prompt)
    eng_translator = _SpyTranslator()
    target_translator = _SpyTranslator()
    response = "Direction: english_to_french\nTranslation:\nBonjour !\n\nNotes:\nnone"
    client = _FakeLLMClient(response)
    usage_events = []

    translator = AutoTranslator(
        console=Console(),
        client=client,
        language_config=config,
        eng_to_target=eng_translator,
        target_to_eng=target_translator,
        prompt_template=config.auto_prompt_template,
        prompt_variable="source_text",
        usage_callback=lambda usage: usage_events.append(usage),
    )

    monkeypatch.setattr(translator, "_collect_multiline_input", lambda: "Hello!")
    translator.run()

    assert eng_translator.calls == [("Hello!", "Bonjour !")]
    assert target_translator.calls == []
    assert usage_events and usage_events[0]["output_tokens"] == 12


def test_auto_translator_handles_target_direction(monkeypatch):
    prompt = "Text:\n{source_text}"
    config = _language_config(prompt)
    eng_translator = _SpyTranslator()
    target_translator = _SpyTranslator()
    response = "Direction: french_to_english\nTranslation:\nHello there\n\nNotes:\nHandled idiom"
    client = _FakeLLMClient(response)

    translator = AutoTranslator(
        console=Console(),
        client=client,
        language_config=config,
        eng_to_target=eng_translator,
        target_to_eng=target_translator,
        prompt_template=config.auto_prompt_template,
        prompt_variable="source_text",
        usage_callback=None,
    )

    monkeypatch.setattr(translator, "_collect_multiline_input", lambda: "Salut !")
    translator.run()

    assert target_translator.calls == [("Salut !", "Hello there")]
    assert eng_translator.calls == []


def test_auto_translator_ignores_notes_without_blank_separator(monkeypatch):
    prompt = "Input:\n{source_text}"
    config = _language_config(prompt)
    eng_translator = _SpyTranslator()
    target_translator = _SpyTranslator()
    response = "Direction: english_to_french\nTranslation:\nBonjour !\nNotes:\nCasual greeting"
    client = _FakeLLMClient(response)

    translator = AutoTranslator(
        console=Console(),
        client=client,
        language_config=config,
        eng_to_target=eng_translator,
        target_to_eng=target_translator,
        prompt_template=config.auto_prompt_template,
        prompt_variable="source_text",
        usage_callback=None,
    )

    monkeypatch.setattr(translator, "_collect_multiline_input", lambda: "Hello!")
    translator.run()

    assert eng_translator.calls == [("Hello!", "Bonjour !")]
    assert target_translator.calls == []


def test_parse_last_direction_match(monkeypatch):
    """When the model preamble contains a wrong Direction:, the parser should use the last one."""
    prompt = "Input:\n{source_text}"
    config = _language_config(prompt)
    eng_translator = _SpyTranslator()
    target_translator = _SpyTranslator()
    # Preamble has wrong direction, final block has correct one
    response = (
        "I think this is french_to_english.\n"
        "Direction: french_to_english\n"
        "Wait, actually it's English.\n\n"
        "Direction: english_to_french\n"
        "Translation:\nBonjour le monde\n\n"
        "Notes:\nnone"
    )
    client = _FakeLLMClient(response)

    translator = AutoTranslator(
        console=Console(),
        client=client,
        language_config=config,
        eng_to_target=eng_translator,
        target_to_eng=target_translator,
        prompt_template=config.auto_prompt_template,
        prompt_variable="source_text",
    )

    monkeypatch.setattr(translator, "_collect_multiline_input", lambda: "Hello world")
    translator.run()

    assert eng_translator.calls == [("Hello world", "Bonjour le monde")]
    assert target_translator.calls == []


def test_sanity_check_rejects_same_language(monkeypatch):
    """If input and translation are nearly identical, user is prompted and can reject."""
    prompt = "Input:\n{source_text}"
    config = _language_config(prompt)
    eng_translator = _SpyTranslator()
    target_translator = _SpyTranslator()
    # Model returns English text as "translation" of English input
    response = "Direction: english_to_french\nTranslation:\nIt is too early for me\n\nNotes:\nnone"
    client = _FakeLLMClient(response)

    translator = AutoTranslator(
        console=Console(),
        client=client,
        language_config=config,
        eng_to_target=eng_translator,
        target_to_eng=target_translator,
        prompt_template=config.auto_prompt_template,
        prompt_variable="source_text",
    )

    monkeypatch.setattr(translator, "_collect_multiline_input", lambda: "It is too early for me")
    # User declines the suspicious translation
    import vocab_builder.core.auto_translator as _at_mod
    monkeypatch.setattr(_at_mod, "read_line", lambda _prompt: "n")
    translator.run()

    assert eng_translator.calls == []
    assert target_translator.calls == []


def test_sanity_check_passes_valid_translation(monkeypatch):
    """A proper foreign-language translation should pass the sanity check."""
    prompt = "Input:\n{source_text}"
    config = _language_config(prompt)
    eng_translator = _SpyTranslator()
    target_translator = _SpyTranslator()
    response = "Direction: english_to_french\nTranslation:\nC'est trop tôt pour moi\n\nNotes:\nnone"
    client = _FakeLLMClient(response)

    translator = AutoTranslator(
        console=Console(),
        client=client,
        language_config=config,
        eng_to_target=eng_translator,
        target_to_eng=target_translator,
        prompt_template=config.auto_prompt_template,
        prompt_variable="source_text",
    )

    monkeypatch.setattr(translator, "_collect_multiline_input", lambda: "It is too early for me")
    translator.run()

    assert eng_translator.calls == [("It is too early for me", "C'est trop tôt pour moi")]


def test_verbose_flag_does_not_break(monkeypatch):
    """The verbose flag should not cause errors during normal operation."""
    prompt = "Input:\n{source_text}"
    config = _language_config(prompt)
    eng_translator = _SpyTranslator()
    target_translator = _SpyTranslator()
    response = "Direction: english_to_french\nTranslation:\nBonjour !\n\nNotes:\nnone"
    client = _FakeLLMClient(response)

    translator = AutoTranslator(
        console=Console(),
        client=client,
        language_config=config,
        eng_to_target=eng_translator,
        target_to_eng=target_translator,
        prompt_template=config.auto_prompt_template,
        prompt_variable="source_text",
        verbose=True,
    )

    monkeypatch.setattr(translator, "_collect_multiline_input", lambda: "Hello!")
    translator.run()

    assert eng_translator.calls == [("Hello!", "Bonjour !")]
