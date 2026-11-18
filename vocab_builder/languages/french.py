from __future__ import annotations

from typing import Dict

from vocab_builder.ai_prompts import AI_PROMPT_TEMPLATE
from vocab_builder.models import normalize_word_key
from .latex_templates import (
    TRANSLATION_DOCUMENT_END,
    VOCAB_DOCUMENT_END,
    translation_document,
    vocab_document,
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

# A new French file starts with this entry.
_SAMPLE_ENTRY = r"""\entry{agaçante}{Unknown}
      {
        \item Annoying, irritating
    \item Exasperating, vexing
    \item Teasing, provocative (in a mildly frustrating way)
      }
      {
        \item Cette musique répétitive est vraiment agaçante. \\ (This repetitive music is really annoying.)
    \item Son attitude agaçante finit par lasser tout le monde. \\ (Her irritating attitude ends up tiring everyone out.)
    \item Elle a un sourire agaçant qui me met mal à l'aise. \\ (She has a vexing smile that makes me uncomfortable.)
      }"""

FRENCH_ENG_TO_FR_PROMPT = """You are a senior English-to-French translator experienced in literary and specialist nonfiction.

Translate the source accurately and idiomatically. Infer its domain, audience, tone, formality, and era, and reproduce them in French. Preserve meaning, agency, logical relations, quantifiers, modality, stance, voice, imagery, ambiguity, rhythm, and historical distance. Do not add, omit, summarize, intensify, soften, or modernize the source.

Translate idioms and wordplay by function when a natural French solution exists. Preserve cultural references, institutions, terminology, and proper names unless an established French equivalent genuinely exists. Infer tu/vous only from evidence in the source; when the relationship is ambiguous, prefer wording that does not invent one.

Preserve paragraphs, verse lines, dialogue attribution, headings, placeholders, inline code, markup, mathematical notation, and other structural elements. Apply normal French punctuation, quotation marks, and spacing. Correct only unmistakable mechanical OCR artifacts; never silently alter names, facts, historical spelling, dialect, or deliberate nonstandard usage.

Return the translation only, without a heading, quotation wrapper, notes, alternatives, or commentary.

English source:
<source_text>
{english_text}
</source_text>"""

FRENCH_FR_TO_ENG_PROMPT = """You are a senior French-to-English translator experienced in literature and specialist nonfiction.

Translate the source accurately and idiomatically. Preserve meaning, agency, logical relations, quantifiers, modality, stance, register, historical distance, voice, imagery, ambiguity, repetitions, and rhetorical force. Do not add, omit, summarize, intensify, soften, or modernize the source.

Write natural English without mechanically smoothing deliberate syntactic pressure or changing rhetorical tense. Translate idioms by function and use established English equivalents for specialist and cultural terms. Preserve the French term or proper name when no natural established equivalent exists.

Preserve paragraphs, verse lines, speaker labels, stage directions, headings, placeholders, inline code, markup, mathematical notation, and other structural elements. Apply normal English punctuation and typography. Correct only unmistakable mechanical OCR artifacts; never silently alter names, facts, historical spelling, dialect, or deliberate nonstandard usage.

Return the translation only, without a heading, quotation wrapper, notes, alternatives, or commentary.

French source:
<source_text>
{french_text}
</source_text>"""

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
    ui_strings=_UI_STRINGS,
    input_validator=_validate_french_text,
    eng_to_target=TranslatorConfig(
        default_filename="EnglishToFrench.tex",
        initial_tex_content=translation_document("engfre", "EN", "FR"),
        final_tex_content=TRANSLATION_DOCUMENT_END,
        prompt_template=FRENCH_ENG_TO_FR_PROMPT,
        prompt_variable="english_text",
        source_label="English",
        target_label="French",
        ui_title="English → French Translator",
        table_headers=("English", "French"),
        latex_commands=("engfre",),
    ),
    target_to_eng=TranslatorConfig(
        default_filename="FrenchToEnglish.tex",
        initial_tex_content=translation_document("freeng", "FR", "EN"),
        final_tex_content=TRANSLATION_DOCUMENT_END,
        prompt_template=FRENCH_FR_TO_ENG_PROMPT,
        prompt_variable="french_text",
        source_label="French",
        target_label="English",
        ui_title="French → English Translator",
        table_headers=("French", "English"),
        latex_commands=("freeng",),
    ),
    vocab=VocabTemplate(
        initial_content=vocab_document("french,english", "Examples"),
        sample_entry=_SAMPLE_ENTRY,
        final_content=VOCAB_DOCUMENT_END,
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
