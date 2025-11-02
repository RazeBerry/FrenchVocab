from __future__ import annotations

from typing import Dict

from ai_prompts import AI_PROMPT_TEMPLATE
from eng_to_fr_latex_templates import (
    INITIAL_ENG_FR_TEX_CONTENT,
    FINAL_ENG_FR_TEX_CONTENT,
    AI_TRANSLATION_PROMPT_TEMPLATE,
)
from fr_to_eng_latex_templates import (
    INITIAL_FR_ENG_TEX_CONTENT,
    FINAL_FR_ENG_TEX_CONTENT,
    FR_TO_ENG_TRANSLATION_PROMPT_TEMPLATE,
)
from latex_templates import INITIAL_TEX_CONTENT, SAMPLE_ENTRY, FINAL_TEX_CONTENT
from .base import (
    LanguageConfig,
    TranslatorConfig,
    VocabTemplate,
    AnkiConfig,
    AnkiCardTemplate,
)
from .anki_shared_styles import get_anki_css


def _validate_french_text(text: str, allow_sentences: bool) -> bool:
    """Validation rules for French input."""
    stripped = text.strip()
    if not stripped:
        return False

    if not allow_sentences:
        base_valid = {"-", "'", "’", "‘"}
        return all(ch.isalpha() or ch.isspace() or ch in base_valid for ch in stripped)

    valid_chars = {
        "-", "'", "’", "‘",          # apostrophes/hyphen
        "–", "—",                    # en/em dash
        ",", ".", ";", ":", "!", "?",  # punctuation
        "(", ")", "[", "]",
        '"', "«", "»", "“", "”",
        "…", "/", "\\",             # ellipsis, slash, backslash (escaped later for LaTeX)
        "%", "$", "€", "#", "&", "+", "*", "@", "=",
    }
    return all(
        ch.isalpha() or ch.isspace() or ch.isdigit() or ch in valid_chars
        for ch in stripped
    )


_UI_STRINGS: Dict[str, str] = {
    "app.title": "French Vocabulary LaTeX Builder",
    "menu.add_word": "Add French word",
    "menu.eng_to_target": "Translate English -> French",
    "menu.target_to_eng": "Translate French -> English",
}

FRENCH_CONFIG = LanguageConfig(
    code="fr",
    display_name="French",
    prompt_template=AI_PROMPT_TEMPLATE,
    vocab_filename="FrenchVocab.tex",
    eng_to_target_filename="EnglishToFrench.tex",
    target_to_eng_filename="FrenchToEnglish.tex",
    latex_babel_languages=("french", "english"),
    ui_strings=_UI_STRINGS,
    input_validator=_validate_french_text,
    eng_to_target=TranslatorConfig(
        default_filename="EnglishToFrench.tex",
        initial_tex_content=INITIAL_ENG_FR_TEX_CONTENT,
        final_tex_content=FINAL_ENG_FR_TEX_CONTENT,
        prompt_template=AI_TRANSLATION_PROMPT_TEMPLATE,
        prompt_variable="english_text",
        source_label="English",
        target_label="French",
        ui_title="English → French Translator",
        table_headers=("English", "French"),
        latex_commands=("engfre",),
    ),
    target_to_eng=TranslatorConfig(
        default_filename="FrenchToEnglish.tex",
        initial_tex_content=INITIAL_FR_ENG_TEX_CONTENT,
        final_tex_content=FINAL_FR_ENG_TEX_CONTENT,
        prompt_template=FR_TO_ENG_TRANSLATION_PROMPT_TEMPLATE,
        prompt_variable="french_text",
        source_label="French",
        target_label="English",
        ui_title="French → English Translator",
        table_headers=("French", "English"),
        latex_commands=("freeng",),
    ),
    vocab=VocabTemplate(
        initial_content=INITIAL_TEX_CONTENT,
        sample_entry=SAMPLE_ENTRY,
        final_content=FINAL_TEX_CONTENT,
        entry_command="\\entry",
    ),
    anki=AnkiConfig(
        deck_namespace="FrenchDeck",
        default_deck_name="French Vocabulary",
        model_seed="FrenchVocabModel/v1",
        model_name="French Vocab Model v1",
        field_names=("French", "Type", "English", "Example"),
        card_templates=(
            AnkiCardTemplate(
                name="Card 1",
                question_format="""
<div class="entry-card entry-card--front">
  <div class="entry-header">
    <div class="entry-word">{{French}}</div>
    {{#Type}}<div class="entry-pos">{{Type}}</div>{{/Type}}
  </div>
</div>
""".strip(),
                answer_format="""
<div class="entry-card entry-card--back">
  <div class="entry-header">
    <div class="entry-word">{{French}}</div>
    {{#Type}}<div class="entry-pos">{{Type}}</div>{{/Type}}
  </div>
  {{#English}}
  <div class="entry-section">
    <div class="entry-section-title">Definitions</div>
    <div class="entry-content">{{{English}}}</div>
  </div>
  {{/English}}
  {{#Example}}
  <div class="entry-section">
    <div class="entry-section-title">Examples</div>
    <div class="entry-content">{{{Example}}}</div>
  </div>
  {{/Example}}
</div>
""".strip(),
            ),
        ),
        card_css=get_anki_css("fr"),
    ),
    aliases=("fr-fr", "france"),
)


__all__ = ["FRENCH_CONFIG"]
