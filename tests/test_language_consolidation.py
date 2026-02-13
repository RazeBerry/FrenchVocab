from languages.base import make_text_validator
from languages.french import FRENCH_CONFIG
from languages.latex_templates import INITIAL_ENG_FR_TEX_CONTENT, INITIAL_FR_ENG_TEX_CONTENT


def test_make_text_validator_allows_typographic_apostrophes_in_words():
    validator = make_text_validator()
    assert validator("café", allow_sentences=False)
    assert validator("aujourd’hui", allow_sentences=False)  # curly apostrophe
    assert validator("porte-monnaie", allow_sentences=False)
    assert not validator("bonjour!", allow_sentences=False)
    assert not validator("123", allow_sentences=False)


def test_make_text_validator_sentence_mode_allows_punctuation_and_digits():
    validator = make_text_validator()
    assert validator("Ceci est une phrase! 123", allow_sentences=True)
    assert not validator("Ceci est une phrase! 123", allow_sentences=False)


def test_make_text_validator_supports_language_specific_quotes():
    base = make_text_validator()
    assert not base("„Hallo‟", allow_sentences=True)

    german = make_text_validator(frozenset({"„", "‟"}))
    assert german("„Hallo‟", allow_sentences=True)


def test_consolidated_latex_translation_templates_are_unescaped_tex():
    eng_fr = INITIAL_ENG_FR_TEX_CONTENT.lstrip()
    assert eng_fr.startswith("\\documentclass")
    assert not eng_fr.startswith("\\\\documentclass")
    assert r"\newcommand{\engfre}" in eng_fr

    fr_eng = INITIAL_FR_ENG_TEX_CONTENT.lstrip()
    assert fr_eng.startswith("\\documentclass")
    assert r"\newcommand{\freeng}" in fr_eng


def test_french_config_uses_consolidated_translation_templates():
    assert FRENCH_CONFIG.eng_to_target.initial_tex_content == INITIAL_ENG_FR_TEX_CONTENT
    assert FRENCH_CONFIG.target_to_eng.initial_tex_content == INITIAL_FR_ENG_TEX_CONTENT
