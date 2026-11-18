import tempfile
from pathlib import Path

import pytest

from vocab_builder.core import VocabBuilder
from vocab_builder.cli.bootstrap import build_app
from vocab_builder.languages import available_language_codes, get_language_config
from vocab_builder.languages.anki_shared_styles import compute_template_hash
from vocab_builder.languages.anki_shared_styles import get_anki_css

ALL_LANGUAGES = available_language_codes()
TRANSLATION_LANGUAGES = [
    code for code in ALL_LANGUAGES if get_language_config(code).supports_translation
]


@pytest.mark.parametrize("language_code", ALL_LANGUAGES)
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


@pytest.mark.parametrize("language_code", ALL_LANGUAGES)
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


@pytest.mark.parametrize("language_code", TRANSLATION_LANGUAGES)
def test_directional_translation_prompts_use_fidelity_contract(language_code):
    cfg = get_language_config(language_code)

    for translator in (cfg.eng_to_target, cfg.target_to_eng):
        assert translator is not None
        prompt = translator.prompt_template
        assert "Preserve meaning, agency, logical relations, quantifiers" in prompt
        assert "historical distance" in prompt
        assert "Return the translation only" in prompt
        assert "<source_text>" in prompt
        assert "Notes (optional)" not in prompt
        assert "contemporary" not in prompt


@pytest.mark.parametrize("language_code", TRANSLATION_LANGUAGES)
def test_auto_translation_prompts_can_decline_ambiguous_direction(language_code):
    prompt = get_language_config(language_code).auto_prompt_template

    assert prompt is not None
    assert "|ambiguous>" in prompt
    assert "do not guess" in prompt
    assert 'write "none" in the Translation field' in prompt


def test_german_translation_prompts_use_correct_quotes_and_nonmechanical_tense():
    cfg = get_language_config("de")
    assert cfg.eng_to_target is not None
    assert cfg.target_to_eng is not None

    assert "„…“" in cfg.eng_to_target.prompt_template
    assert "„...\"" not in cfg.eng_to_target.prompt_template
    assert "do not apply a fixed Perfekt-to-simple-past" in cfg.target_to_eng.prompt_template


@pytest.mark.parametrize("language_code", ALL_LANGUAGES)
def test_spawned_empty_latex_templates_include_placeholder_item(language_code):
    cfg = get_language_config(language_code)

    assert r"\item[]\relax" in cfg.vocab.initial_content


@pytest.mark.parametrize("language_code", TRANSLATION_LANGUAGES)
def test_bilingual_templates_include_translation_placeholders(language_code):
    cfg = get_language_config(language_code)

    assert cfg.eng_to_target is not None
    assert cfg.target_to_eng is not None
    assert r"\item[]\relax" in cfg.eng_to_target.initial_tex_content
    assert r"\item[]\relax" in cfg.target_to_eng.initial_tex_content


def test_language_configs_include_template_versions():
    for code in ALL_LANGUAGES:
        cfg = get_language_config(code)
        templates = [
            {"name": tpl.name, "qfmt": tpl.question_format, "afmt": tpl.answer_format}
            for tpl in cfg.anki.card_templates
        ]
        expected_hash = compute_template_hash(templates, cfg.anki.card_css)
        assert cfg.anki.version_id == expected_hash


@pytest.mark.parametrize(
    ("language_code", "version_id"),
    [
        ("fr", "1a83c00381b2c370be0cab4c825208e55441f125"),
        ("de", "8cd0d3749bb9216417e7d496fa8d5c95572bb028"),
    ],
)
def test_existing_bilingual_decks_keep_their_template_version(language_code, version_id):
    """An exported deck records this hash, and a different one rebuilds the
    whole deck on the next export (core/anki_manager.py). These are the
    versions shipped before the card was built from its field name."""
    assert get_language_config(language_code).anki.version_id == version_id


@pytest.mark.parametrize(
    "language_code",
    [code for code in ALL_LANGUAGES if get_language_config(code).learning_mode == "bilingual"],
)
def test_bilingual_card_shows_the_headword_field(language_code):
    anki = get_language_config(language_code).anki
    headword = "{{" + anki.field_names[0] + "}}"

    for template in anki.card_templates:
        assert headword in template.question_format
        assert headword in template.answer_format


@pytest.mark.parametrize(
    ("language_code", "learner"),
    [
        ("fr", "an advanced learner aiming at DALF C2 register awareness"),
        ("de", "an advanced learner aiming at Goethe C2 register awareness"),
    ],
)
def test_composition_coach_grades_at_the_learners_level(language_code, learner):
    cfg = get_language_config(language_code)
    persona = (
        f"You are a rigorous but warm {cfg.display_name} composition coach for {learner}.\n"
    )

    assert cfg.composition.grading_prompt_template.startswith(persona)
    assert cfg.composition.reverse_grading_prompt_template.startswith(persona)
    assert cfg.composition.ui_title == f"{cfg.display_name} Composition Practice"


@pytest.mark.parametrize("language_code", ALL_LANGUAGES)
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


def test_french_prompt_uses_flexible_aligned_lexical_contract():
    prompt = get_language_config("fr").prompt_template
    normalized_prompt = " ".join(prompt.split())

    assert "one lexical identity" in normalized_prompt
    assert "lexicalized inflected form" in normalized_prompt
    assert "one sense by default" in normalized_prompt
    assert "exactly one example for each Definitions entry" in normalized_prompt
    assert "same headword and part of speech" in normalized_prompt
    assert "never force a future tense sentence" in normalized_prompt
    assert "Allocate your three definition slots" not in normalized_prompt
    assert "use Present for 1" not in normalized_prompt


def test_german_prompt_shares_the_measured_lexical_contract():
    """The German prompt was a generation behind: it still filled three slots,
    forced Present/Perfekt/Futur examples, and invited wordplay speculation.
    The panel in scripts/prompt_panel measured the ported contract before it
    shipped; these lines are what the panel proved."""
    prompt = get_language_config("de").prompt_template
    normalized_prompt = " ".join(prompt.split())

    assert "one lexical identity" in normalized_prompt
    assert "one sense by default" in normalized_prompt
    assert "exactly one example for each Definitions entry" in normalized_prompt
    assert "never force a future tense sentence" in normalized_prompt
    assert "Never define a form that no serious dictionary lists" in normalized_prompt
    assert "Allocate your three definition slots" not in normalized_prompt
    assert "use Present for 1" not in normalized_prompt
    assert "double entendre" not in normalized_prompt
