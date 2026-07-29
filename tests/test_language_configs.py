import tempfile
from pathlib import Path

import pytest

from vocab_builder.core import VocabBuilder
from vocab_builder.cli.bootstrap import build_app
from vocab_builder.languages import available_language_codes, get_language_config
from vocab_builder.languages.anki_shared_styles import compute_template_hash
from vocab_builder.languages.anki_shared_styles import get_anki_css


@pytest.mark.parametrize("language_code", ["fr", "de", "en"])
def test_builder_initializes_for_language(language_code, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / f"{language_code}_vocab.tex"
        builder = VocabBuilder(
            str(tex_path),
            provider="gemini",
            verbose=False,
            language=language_code,
        )
        assert builder.language_code == language_code
        assert builder.entry_command.startswith("\\")
        builder.create_initial_tex_file()
        assert tex_path.exists()
        content = tex_path.read_text(encoding="utf-8").lstrip()
        assert content.startswith("\\documentclass")
        assert not content.startswith("\\\\documentclass")


def test_available_language_codes_include_bundled_languages():
    codes = available_language_codes()
    assert {"fr", "de", "en"}.issubset(codes)


@pytest.mark.parametrize("language_code", ["fr", "de", "en"])
def test_build_app_sets_language(monkeypatch, language_code, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    latex_path = tmp_path / f"{language_code}_cli.tex"
    builder = build_app(
        language_code,
        latex_file=str(latex_path),
        provider="gemini",
        verbose=False,
    )
    assert builder.language_code == language_code
    assert builder.latex_file.exists()


def test_german_translator_config_has_dedicated_macros():
    cfg = get_language_config("de")
    assert cfg.eng_to_target.prompt_variable == "english_text"
    assert cfg.target_to_eng.prompt_variable == "german_text"
    assert "engde" in cfg.eng_to_target.latex_commands
    assert "deeng" in cfg.target_to_eng.latex_commands
    assert "English to German" in cfg.eng_to_target.initial_tex_content
    assert "German to English" in cfg.target_to_eng.initial_tex_content


@pytest.mark.parametrize("language_code", ["fr", "de", "en"])
def test_spawned_empty_latex_templates_include_placeholder_item(language_code):
    cfg = get_language_config(language_code)

    assert r"\item[]\relax" in cfg.vocab.initial_content


@pytest.mark.parametrize("language_code", ["fr", "de"])
def test_bilingual_templates_include_translation_placeholders(language_code):
    cfg = get_language_config(language_code)

    assert cfg.eng_to_target is not None
    assert cfg.target_to_eng is not None
    assert r"\item[]\relax" in cfg.eng_to_target.initial_tex_content
    assert r"\item[]\relax" in cfg.target_to_eng.initial_tex_content


def test_language_configs_include_template_versions():
    for code in ["fr", "de", "en"]:
        cfg = get_language_config(code)
        templates = [
            {"name": tpl.name, "qfmt": tpl.question_format, "afmt": tpl.answer_format}
            for tpl in cfg.anki.card_templates
        ]
        expected_hash = compute_template_hash(templates, cfg.anki.card_css)
        assert cfg.anki.version_id == expected_hash


@pytest.mark.parametrize("language_code", ["fr", "de", "en"])
def test_language_configs_use_shared_css(language_code):
    cfg = get_language_config(language_code)
    assert cfg.anki.card_css == get_anki_css(language_code)


def test_english_config_is_monolingual_with_dedicated_anki_fields():
    cfg = get_language_config("en")

    assert cfg.learning_mode == "monolingual"
    assert cfg.supports_translation is False
    assert cfg.eng_to_target is None
    assert cfg.target_to_eng is None
    assert cfg.vocab_filename == "EnglishVocab.tex"
    assert cfg.anki.deck_namespace == "EnglishDeck"
    assert cfg.anki.default_deck_name == "English Vocabulary"
    assert tuple(cfg.anki.field_names) == ("Word", "Type", "Definitions", "Examples")
    assert "{{Word}}" in cfg.anki.card_templates[0].question_format
