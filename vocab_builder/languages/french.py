from __future__ import annotations

from typing import Dict

from vocab_builder.ai_prompts import AI_PROMPT_TEMPLATE
from vocab_builder.models import normalize_word_key
from .latex_templates import (
    # Main vocabulary templates
    INITIAL_TEX_CONTENT,
    SAMPLE_ENTRY,
    FINAL_TEX_CONTENT,
    # English → French templates
    INITIAL_ENG_FR_TEX_CONTENT,
    FINAL_ENG_FR_TEX_CONTENT,
    AI_TRANSLATION_PROMPT_TEMPLATE,
    # French → English templates
    INITIAL_FR_ENG_TEX_CONTENT,
    FINAL_FR_ENG_TEX_CONTENT,
    FR_TO_ENG_TRANSLATION_PROMPT_TEMPLATE,
)
from .base import (
    LanguageConfig,
    TranslatorConfig,
    VocabTemplate,
    AnkiConfig,
    composition_config,
    make_text_validator,
)
from .anki_shared_styles import (
    bilingual_card_templates,
    compute_template_hash,
    get_anki_css,
)

# French uses the base character set (no extra characters needed)
_validate_french_text = make_text_validator()

_UI_STRINGS: Dict[str, str] = {
    "app.title": "French Vocabulary LaTeX Builder",
    "menu.add_word": "Add French word",
    "menu.eng_to_target": "Translate English -> French",
    "menu.target_to_eng": "Translate French -> English",
}

FRENCH_CARD_TEMPLATES = bilingual_card_templates("French")
FRENCH_CARD_CSS = get_anki_css("fr")
FRENCH_CARD_VERSION = compute_template_hash(
    [
        {"name": tpl.name, "qfmt": tpl.question_format, "afmt": tpl.answer_format}
        for tpl in FRENCH_CARD_TEMPLATES
    ],
    FRENCH_CARD_CSS,
)

FRENCH_AUTO_TRANSLATOR_PROMPT = """
You are an expert bilingual assistant for English and French.

STEP 1 — Detect the source language:
Examine the input text for linguistic signals.
• French signals: accented characters (é è ê ë à â ù û ô î ï ç), French function words (le, la, les, un, une, des, est, sont, je, tu, il, nous, vous, ils, de, du, au, aux, pas, ne, que, qui, avec, pour, dans, sur, ce, cette), French spelling patterns.
• English signals: English function words (the, is, are, was, were, have, has, do, does, not, and, but, for, with, this, that, it, I, we, they), English spelling patterns.
Classify the input as English or French only when the linguistic evidence is sufficient. For a genuinely ambiguous word, name, abbreviation, or fragment, do not guess; classify it as ambiguous.

STEP 2 — When the direction is known, translate into the opposite language accurately and idiomatically. Preserve meaning, agency, logical relations, quantifiers, modality, stance, register, historical distance, voice, imagery, ambiguity, and structural formatting. Translate idioms by function, but do not broadly domesticate cultural references or institutions. Preserve proper names and established specialist terminology. Correct only unmistakable mechanical OCR artifacts; never alter names, facts, historical spelling, dialect, or deliberate nonstandard usage. Apply normal target-language punctuation and typography while preserving paragraphs, verse lines, dialogue attribution, headings, placeholders, inline code, markup, and mathematical notation.

When the direction is ambiguous, do not translate and write "none" in the Translation field.

No preamble, no extra text before the template. Respond EXACTLY with:

Direction: <english_to_french|french_to_english|ambiguous>
Translation:
<translation text preserving structural formatting, or "none" when ambiguous>

Notes:
<when ambiguous, briefly ask the user to choose a direction; otherwise write "none">

Input data:
<source_text>
{source_text}
</source_text>
""".strip()


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
        card_templates=FRENCH_CARD_TEMPLATES,
        card_css=FRENCH_CARD_CSS,
        version_id=FRENCH_CARD_VERSION,
    ),
    headword_key=normalize_word_key,
    composition=composition_config(
        "French", "an advanced learner aiming at DALF C2 register awareness"
    ),
    aliases=("fr-fr", "france"),
    auto_prompt_template=FRENCH_AUTO_TRANSLATOR_PROMPT,
    auto_prompt_variable="source_text",
    auto_direction_tokens=("english_to_french", "french_to_english"),
)


__all__ = ["FRENCH_CONFIG"]
