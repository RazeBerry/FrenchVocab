from __future__ import annotations

from typing import Dict

from vocab_builder.ai_prompts import GERMAN_PROMPT_TEMPLATE
from .base import (
    CompositionConfig,
    LanguageConfig,
    TranslatorConfig,
    VocabTemplate,
    AnkiConfig,
    AnkiCardTemplate,
    make_text_validator,
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

# German has additional quote characters: „ (opening) and “ (closing)
_validate_german_text = make_text_validator(frozenset({"„", "“"}))

_UI_STRINGS: Dict[str, str] = {
    "app.title": "German Vocabulary LaTeX Builder",
    "menu.add_word": "Add German word",
    "menu.eng_to_target": "Translate English -> German",
    "menu.target_to_eng": "Translate German -> English",
    "menu.display_all": "Display all German words",
    "menu.anki_export": "Export German words to Anki",
    "menu.anki_reconcile": "Reconcile Anki exports (German -> English)",
}

GERMAN_ENG_TO_DE_PROMPT = """You are a senior English-to-German translator experienced in literary and specialist nonfiction.

Translate the source accurately and idiomatically. Infer its domain, audience, tone, formality, and era, and reproduce them in German. Preserve meaning, agency, logical relations, quantifiers, modality, stance, voice, imagery, ambiguity, rhythm, and historical distance. Do not add, omit, summarize, intensify, soften, or modernize the source, and do not manufacture archaic spelling.

Translate idioms and wordplay by function when a natural German solution exists. Preserve cultural references, institutions, terminology, and proper names unless an established German equivalent genuinely exists. Infer du/Sie only from evidence in the source; when the relationship is ambiguous, prefer wording that does not invent one.

Preserve paragraphs, verse lines, dialogue attribution, speaker labels, headings, placeholders, inline code, markup, mathematical notation, and other structural elements. Apply normal German punctuation and typography, including „…“, or »…« when required by the source or house style. Correct only unmistakable mechanical OCR artifacts; never silently alter names, facts, historical spelling, dialect, or deliberate nonstandard usage.

Return the translation only, without a heading, quotation wrapper, notes, alternatives, or commentary.

English source:
<source_text>
{english_text}
</source_text>"""

GERMAN_DE_TO_ENG_PROMPT = """You are a senior German-to-English translator experienced in literary and specialist nonfiction.

Translate the source accurately and idiomatically. Preserve meaning, agency, logical relations, quantifiers, modality, stance, register, historical distance, voice, imagery, ambiguity, rhetorical devices, and deliberate syntactic pressure. Do not add, omit, summarize, intensify, soften, or modernize the source.

Choose English tense and reported-speech constructions according to their discourse function. Preserve temporal viewpoint, reportedness, and evidential distance; do not apply a fixed Perfekt-to-simple-past or Konjunktiv-I-to-backshift rule. Translate idioms by function while retaining salient imagery. Use established English terminology for German institutions when available, and retain the German term or proper name when no natural equivalent exists.

Preserve paragraphs, verse lines, speaker labels, stage directions, headings, placeholders, inline code, markup, mathematical notation, numbers, dates, and other structural elements. Apply normal English punctuation and typography. Correct only unmistakable mechanical OCR artifacts; never silently alter names, facts, historical spelling, dialect, or deliberate nonstandard usage.

Return the translation only, without a heading, quotation wrapper, notes, alternatives, or commentary.

German source:
<source_text>
{german_text}
</source_text>"""

_CARD_FRONT_TEMPLATE = """
<div class="entry-card entry-card--front">
  <div class="entry-header">
    <div class="entry-word">{{German}}</div>
    {{#Type}}<div class="entry-pos">{{Type}}</div>{{/Type}}
  </div>
</div>
""".strip()

# Use double braces so Anki escapes HTML; exporter supplies sanitized text.
_CARD_BACK_TEMPLATE = """
<div class="entry-card entry-card--back">
  <div class="entry-header">
    <div class="entry-word">{{German}}</div>
    {{#Type}}<div class="entry-pos">{{Type}}</div>{{/Type}}
  </div>
  {{#English}}
  <div class="entry-section">
    <div class="entry-section-title">Definitions</div>
    <div class="entry-content">{{English}}</div>
  </div>
  {{/English}}
  {{#Example}}
  <div class="entry-section">
    <div class="entry-section-title">Examples</div>
    <div class="entry-content">{{Example}}</div>
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

GERMAN_AUTO_TRANSLATOR_PROMPT = """
You are an expert bilingual assistant for English and German.

STEP 1 — Detect the source language:
Examine the input text for linguistic signals.
• German signals: umlauts (ä ö ü), ß, German function words (der, die, das, ist, und, nicht, ein, eine, ich, wir, haben, werden, auch, für, mit, auf), German sentence structure.
• English signals: English function words (the, is, are, was, were, have, has, do, does, not, and, but, for, with, this, that, it, I, we, they), English spelling patterns.
When function-word signals are absent, use spelling, morphology, capitalization, ß, and umlauts as evidence, but do not treat capitalization alone as decisive. For a genuinely ambiguous word, name, abbreviation, headline, or fragment, do not guess; classify it as ambiguous.

STEP 2 — When the direction is known, translate into the opposite language accurately and idiomatically. Preserve meaning, agency, logical relations, quantifiers, modality, stance, register, historical distance, voice, imagery, ambiguity, and structural formatting. Translate idioms by function, but do not broadly domesticate cultural references or institutions. Preserve proper names and established specialist terminology. Choose tense and reported-speech constructions by discourse function rather than a fixed grammatical mapping. Correct only unmistakable mechanical OCR artifacts; never alter names, facts, historical spelling, dialect, or deliberate nonstandard usage. Apply normal target-language punctuation and typography while preserving paragraphs, verse lines, speaker labels, stage directions, headings, placeholders, inline code, markup, and mathematical notation.

When the direction is ambiguous, do not translate and write "none" in the Translation field.

No preamble, no extra text before the template. Respond EXACTLY with:

Direction: <english_to_german|german_to_english|ambiguous>
Translation:
<translation text preserving structural formatting, or "none" when ambiguous>

Notes:
<when ambiguous, briefly ask the user to choose a direction; otherwise write "none">

Input data:
<source_text>
{source_text}
</source_text>
""".strip()

GERMAN_COMPOSITION_GRADING_PROMPT = """
You are a rigorous but warm German composition coach for an advanced learner aiming at Goethe C2 register awareness.

Grade one short German composition. The learner was asked to use the target words below. Judge whether each target word is used idiomatically in context, not merely present. Give reasons for every correction and one stronger alternative phrasing. Keep the feedback concise and practical.

Target words:
{target_words}

Vocabulary details from the learner's own list:
{word_details}

Learner attempt:
{user_text}

Respond in plain text with exactly these section headers. Do not add any other headers.

Corrected Text:
<full corrected German attempt>

English Gloss:
<natural English gloss of the corrected German attempt>

Corrections:
1. "<learner wording>" -> "<corrected wording>"
   Why: <brief reason>
   Alternative: <stronger idiomatic phrasing>

Word Verdicts:
- <target word>: <correct|incorrect|not_used>

Unknown Word Candidates:
- <German word not already in the target list>: <English gloss>

Register: <consistent|mixed|too informal|too formal, with a short note if needed>

If there are no corrections or unknown candidates, write "none" in that section. Preserve a coach-with-reasons voice.
""".strip()

GERMAN_REVERSE_COMPOSITION_GRADING_PROMPT = """
You are a rigorous but warm German composition coach for an advanced learner aiming at Goethe C2 register awareness.

Grade one short German reverse-translation attempt. The learner saw an English sentence from their own vocabulary example and translated it into German. Compare the attempt with the stored German reference, but accept exact matches and idiomatic equivalent variants; the stored reference is not the only acceptable answer. Judge whether the sampled target word is produced idiomatically in context, including natural inflected or closely equivalent forms. Give reasons for every correction and one stronger alternative phrasing. Keep the feedback concise and practical.

Target word:
{target_word}

Vocabulary details from the learner's own list:
{word_details}

English source shown to the learner:
{source_english}

Stored German reference:
{reference_target}

Learner attempt:
{user_text}

Respond in plain text with exactly these section headers. Do not add any other headers.

Corrected Text:
<full corrected German attempt>

Corrections:
1. "<learner wording>" -> "<corrected wording>"
   Why: <brief reason>
   Alternative: <stronger idiomatic phrasing>

Word Verdicts:
- <target word>: <correct|incorrect|not_used>

Unknown Word Candidates:
- <German word not already in the target list>: <English gloss>

Register: <consistent|mixed|too informal|too formal, with a short note if needed>

If there are no corrections or unknown candidates, write "none" in that section. Preserve a coach-with-reasons voice.
""".strip()


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
    composition=CompositionConfig(
        grading_prompt_template=GERMAN_COMPOSITION_GRADING_PROMPT,
        reverse_grading_prompt_template=GERMAN_REVERSE_COMPOSITION_GRADING_PROMPT,
        ui_title="German Composition Practice",
    ),
    aliases=("de-de", "german"),
    auto_prompt_template=GERMAN_AUTO_TRANSLATOR_PROMPT,
    auto_prompt_variable="source_text",
    auto_direction_tokens=("english_to_german", "german_to_english"),
)


__all__ = ["GERMAN_CONFIG"]
