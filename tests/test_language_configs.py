import tempfile
from pathlib import Path

import pytest

import FrenchVocab
from cli.bootstrap import build_app
from languages import available_language_codes, get_language_config
from languages.anki_shared_styles import compute_template_hash
from languages.anki_shared_styles import get_anki_css


@pytest.mark.parametrize("language_code", ["fr", "de"])
def test_builder_initializes_for_language(language_code, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x" * 40)
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / f"{language_code}_vocab.tex"
        builder = FrenchVocab.FrenchVocabBuilder(
            str(tex_path),
            provider="gemini",
            verbose=False,
            language=language_code,
        )
        assert builder.language_code == language_code
        assert builder.entry_command.startswith("\\")
        builder.create_initial_tex_file()
        assert tex_path.exists()


def test_available_language_codes_include_german():
    codes = available_language_codes()
    assert "fr" in codes
    assert "de" in codes


@pytest.mark.parametrize("language_code", ["fr", "de"])
def test_build_app_sets_language(monkeypatch, language_code, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "x" * 40)
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


def test_language_configs_include_template_versions():
    for code in ["fr", "de"]:
        cfg = get_language_config(code)
        templates = [
            {"name": tpl.name, "qfmt": tpl.question_format, "afmt": tpl.answer_format}
            for tpl in cfg.anki.card_templates
        ]
        expected_hash = compute_template_hash(templates, cfg.anki.card_css)
        assert cfg.anki.version_id == expected_hash


def test_french_config_uses_shared_css():
    cfg = get_language_config("fr")
    assert cfg.anki.card_css == get_anki_css("fr")


def test_german_config_uses_shared_css():
    cfg = get_language_config("de")
    assert cfg.anki.card_css == get_anki_css("de")
