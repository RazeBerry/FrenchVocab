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
from .anki_shared_styles import get_anki_css, compute_template_hash


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

GERMAN_ENG_TO_DE_PROMPT = """You are an experienced English->German translator equally comfortable with literary, technical, and marketing texts. Derive the domain, target audience, formality, tone, and era directly from the source and recreate them authentically in German. Preserve the author's intent, emotional register, rhythm, and narrative voice. Recast idioms, cultural references, humor, and wordplay so they feel native to contemporary German readers while staying faithful to meaning.

Before translating, observe any punctuation, typography, markdown, inline code, mathematical notation, HTML tags, placeholders, or dialogue markers. Copy this scaffolding exactly unless idiomatic German requires a minimal adjustment; never invent new structure. Keep product names, terminology, and proper nouns unchanged unless a widely used German equivalent exists, and respect capitalization, honorifics, and quotation style. When regional cues appear, adopt the matching German variant; otherwise default to neutral Standarddeutsch.

Output only:
German translation: <single cohesive translation mirroring paragraph and line breaks>
Notes (optional): <use only to flag genuine ambiguities, justify a significant adaptation, or offer a concise alternate phrasing>

If the source allows multiple plausible readings, pick the interpretation that best fits context and mention the alternative briefly in Notes. Do not apologize or describe your process; deliver a polished translation.

English source:
{english_text}
"""

GERMAN_DE_TO_ENG_PROMPT = """Translate the following German text into idiomatic, context-appropriate English. Preserve register, tone, and rhetorical devices (questions, exclamations, dashes) while keeping paragraph and line breaks. Detect idioms, figurative language, and fixed expressions: when the source is idiomatic, deliver an equally idiomatic English expression at the same register; switch to a faithful literal rendering only when an idiomatic counterpart would distort meaning, keeping notable imagery intact. Favour fluent English phrasing over word-for-word translations, yet retain proper nouns and culture-specific terms when no natural equivalent exists. Produce only the English translation—no commentary, no quotation marks.

German Text:
"{german_text}"

English Translation:"""

_CARD_FRONT_TEMPLATE = """
<div class="entry-card entry-card--front">
  <div class="entry-header">
    <div class="entry-word">{{German}}</div>
    {{#Type}}<div class="entry-pos">{{Type}}</div>{{/Type}}
  </div>
</div>
""".strip()

_CARD_BACK_TEMPLATE = """
<div class="entry-card entry-card--back">
  <div class="entry-header">
    <div class="entry-word">{{German}}</div>
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
""".strip()

GERMAN_CARD_TEMPLATES = (
    AnkiCardTemplate(
        name="Card 1",
        question_format=_CARD_FRONT_TEMPLATE,
        answer_format=_CARD_BACK_TEMPLATE,
    ),
)
GERMAN_CARD_CSS = get_anki_css("de")
GERMAN_CARD_VERSION = compute_template_hash(
    [
        {"name": tpl.name, "qfmt": tpl.question_format, "afmt": tpl.answer_format}
        for tpl in GERMAN_CARD_TEMPLATES
    ],
    GERMAN_CARD_CSS,
)


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
        card_templates=GERMAN_CARD_TEMPLATES,
        card_css=GERMAN_CARD_CSS,
        version_id=GERMAN_CARD_VERSION,
    ),
    aliases=("de-de", "german"),
)


__all__ = ["GERMAN_CONFIG"]
