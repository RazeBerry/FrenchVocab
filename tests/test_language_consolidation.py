from vocab_builder.languages.base import make_text_validator
from vocab_builder.languages.french import FRENCH_CONFIG
from vocab_builder.languages.german import GERMAN_CONFIG
from vocab_builder.languages.german_tex import (
    GERMAN_INITIAL_TEX_CONTENT,
    INITIAL_DE_ENG_TEX_CONTENT,
    INITIAL_ENG_DE_TEX_CONTENT,
)
from vocab_builder.languages.latex_templates import INITIAL_ENG_FR_TEX_CONTENT, INITIAL_FR_ENG_TEX_CONTENT


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
    assert not base("„Hallo“", allow_sentences=True)

    german = make_text_validator(frozenset({"„", "“"}))
    assert german("„Hallo“", allow_sentences=True)
    assert not german("„Hallo‟", allow_sentences=True)


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


def test_german_latex_templates_are_unescaped_tex():
    vocab = GERMAN_INITIAL_TEX_CONTENT.lstrip()
    assert vocab.startswith("\\documentclass")
    assert not vocab.startswith("\\\\documentclass")
    assert r"\newcommand{\entry}" in vocab

    eng_de = INITIAL_ENG_DE_TEX_CONTENT.lstrip()
    assert eng_de.startswith("\\documentclass")
    assert not eng_de.startswith("\\\\documentclass")
    assert r"\newcommand{\engde}" in eng_de

    de_eng = INITIAL_DE_ENG_TEX_CONTENT.lstrip()
    assert de_eng.startswith("\\documentclass")
    assert not de_eng.startswith("\\\\documentclass")
    assert r"\newcommand{\deeng}" in de_eng


def test_german_config_uses_dedicated_unescaped_templates():
    assert GERMAN_CONFIG.vocab.initial_content == GERMAN_INITIAL_TEX_CONTENT
    assert GERMAN_CONFIG.eng_to_target.initial_tex_content == INITIAL_ENG_DE_TEX_CONTENT
    assert GERMAN_CONFIG.target_to_eng.initial_tex_content == INITIAL_DE_ENG_TEX_CONTENT
