import pytest

from vocab_builder.languages import available_language_codes, get_language_config
from vocab_builder.languages.base import make_text_validator

TRANSLATION_LANGUAGES = [
    code for code in available_language_codes() if get_language_config(code).supports_translation
]


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


@pytest.mark.parametrize("language_code", TRANSLATION_LANGUAGES)
def test_translation_documents_define_their_pair_macro_in_unescaped_tex(language_code):
    cfg = get_language_config(language_code)

    for translator in (cfg.eng_to_target, cfg.target_to_eng):
        document = translator.initial_tex_content.lstrip()
        assert document.startswith("\\documentclass")
        assert not document.startswith("\\\\documentclass")
        assert "\\newcommand{\\" + translator.latex_commands[0] + "}[2]" in document
