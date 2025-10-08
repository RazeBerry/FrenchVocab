from __future__ import annotations

from typing import Dict

from ai_prompts import GERMAN_PROMPT_TEMPLATE
from .base import (
    LanguageConfig,
    TranslatorConfig,
    VocabTemplate,
    AnkiConfig,
    AnkiCardTemplate,
)
from .german_tex import (
    GERMAN_INITIAL_TEX_CONTENT,
    GERMAN_FINAL_TEX_CONTENT,
    INITIAL_ENG_DE_TEX_CONTENT,
    FINAL_ENG_DE_TEX_CONTENT,
    INITIAL_DE_ENG_TEX_CONTENT,
    FINAL_DE_ENG_TEX_CONTENT,
)


def _validate_german_text(text: str, allow_sentences: bool) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    if not allow_sentences:
        base_valid = {"-", "'", "’", "‘"}
        return all(ch.isalpha() or ch.isspace() or ch in base_valid for ch in stripped)

    valid_chars = {
        "-", "'", "’", "‘",
        "–", "—",
        ",", ".", ";", ":", "!", "?",
        "(", ")", "[", "]",
        '"', "«", "»", "“", "”", "„", "‟",
        "…", "/", "\\",
        "%", "$", "€", "#", "&", "+", "*", "@", "=",
    }
    return all(
        ch.isalpha() or ch.isspace() or ch.isdigit() or ch in valid_chars
        for ch in stripped
    )


_UI_STRINGS: Dict[str, str] = {
    "app.title": "German Vocabulary LaTeX Builder",
    "menu.add_word": "Add German word",
    "menu.eng_to_target": "Translate English -> German",
    "menu.target_to_eng": "Translate German -> English",
    "menu.display_all": "Display all German words",
    "menu.anki_export": "Export German words to Anki",
    "menu.anki_reconcile": "Reconcile Anki exports (German -> English)",
}

GERMAN_ENG_TO_DE_PROMPT = """Translate the following English text accurately and naturally into German. Provide only the German translation, without any introductory phrases, explanations, or quotation marks.

English Text: "{english_text}"

German Translation:"""

GERMAN_DE_TO_ENG_PROMPT = """Translate the following German text accurately and naturally into English. Provide only the English translation, without any introductory phrases, explanations, or quotation marks.

German: "{german_text}"

English Translation:"""

GERMAN_CONFIG = LanguageConfig(
    code="de",
    display_name="German",
    prompt_template=GERMAN_PROMPT_TEMPLATE,
    vocab_filename="GermanVocab.tex",
    eng_to_target_filename="EnglishToGerman.tex",
    target_to_eng_filename="GermanToEnglish.tex",
    latex_babel_languages=("ngerman", "english"),
    ui_strings=_UI_STRINGS,
    input_validator=_validate_german_text,
    eng_to_target=TranslatorConfig(
        default_filename="EnglishToGerman.tex",
        initial_tex_content=INITIAL_ENG_DE_TEX_CONTENT,
        final_tex_content=FINAL_ENG_DE_TEX_CONTENT,
        prompt_template=GERMAN_ENG_TO_DE_PROMPT,
        prompt_variable="english_text",
        source_label="English",
        target_label="German",
        ui_title="English → German Translator",
        table_headers=("English", "German"),
        latex_commands=("engde", "engfre"),
    ),
    target_to_eng=TranslatorConfig(
        default_filename="GermanToEnglish.tex",
        initial_tex_content=INITIAL_DE_ENG_TEX_CONTENT,
        final_tex_content=FINAL_DE_ENG_TEX_CONTENT,
        prompt_template=GERMAN_DE_TO_ENG_PROMPT,
        prompt_variable="german_text",
        source_label="German",
        target_label="English",
        ui_title="German → English Translator",
        table_headers=("German", "English"),
        latex_commands=("deeng", "freeng"),
    ),
    vocab=VocabTemplate(
        initial_content=GERMAN_INITIAL_TEX_CONTENT,
        sample_entry="",
        final_content=GERMAN_FINAL_TEX_CONTENT,
        entry_command="\\entry",
    ),
    anki=AnkiConfig(
        deck_namespace="GermanDeck",
        default_deck_name="German Vocabulary",
        model_seed="GermanVocabModel/v1",
        model_name="German Vocab Model v1",
        field_names=("German", "Type", "English", "Example"),
        card_templates=(
            AnkiCardTemplate(
                name="Card 1",
                question_format="{{German}}<br>{{Type}}",
                answer_format="{{FrontSide}}<hr id=\"answer\">{{English}}<br><br>Example:<br>{{Example}}",
            ),
        ),
    ),
    aliases=("de-de", "german"),
)


__all__ = ["GERMAN_CONFIG"]
