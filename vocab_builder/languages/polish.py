from __future__ import annotations

import unicodedata

from vocab_builder.ai_prompts import POLISH_PROMPT_TEMPLATE
from vocab_builder.models import normalize_word_key
from .base import (
    LanguageConfig,
    TranslatorConfig,
    VocabTemplate,
    AnkiConfig,
    composition_config,
    make_text_validator,
)
from .latex_templates import (
    TRANSLATION_DOCUMENT_END,
    VOCAB_DOCUMENT_END,
    translation_document,
    vocab_document,
)
from .anki_shared_styles import bilingual_card_templates, get_anki_css

# Polish opens a quotation with „; the closing ” is already in the base set.
_validate_polish_text = make_text_validator(frozenset({"„"}))

# Each Polish letter keys as its base letter followed by a character that sorts
# after every ASCII letter, so it files right after the plain letter's words
# (kawa before kąt, zupa before źle before żaba) and under the plain letter's
# rail, and so diacritics keep their identity (sad and sąd are two entries).
_POLISH_LETTER_KEYS = str.maketrans(
    {
        "ą": "a{",
        "ć": "c{",
        "ę": "e{",
        "ł": "l{",
        "ń": "n{",
        "ó": "o{",
        "ś": "s{",
        "ź": "z{",
        "ż": "z|",
    }
)


def polish_headword_key(word: str) -> str:
    """Return the Polish headword key (docs/vocabulary.md)."""
    composed = unicodedata.normalize("NFC", word).lower()
    return normalize_word_key(composed.translate(_POLISH_LETTER_KEYS))


POLISH_ENG_TO_PL_PROMPT = """You are a senior English-to-Polish translator experienced in literary and specialist nonfiction.

Translate the source accurately and idiomatically. Infer its domain, audience, tone, formality, and era, and reproduce them in Polish. Preserve meaning, agency, logical relations, quantifiers, modality, stance, voice, imagery, ambiguity, rhythm, and historical distance. Do not add, omit, summarize, intensify, soften, or modernize the source, and do not manufacture archaic spelling.

Translate idioms and wordplay by function when a natural Polish solution exists. Preserve cultural references, institutions, terminology, and proper names unless an established Polish equivalent genuinely exists. Infer ty or Pan/Pani only from evidence in the source; when the relationship is ambiguous, prefer wording that does not invent one. Mark the gender of a speaker or addressee in past-tense and other gendered forms only from evidence in the source; when it is unknown, prefer a construction that leaves it unmarked. Do not render English articles mechanically with ten or jakiś; use a determiner only where Polish needs one. Choose each verb's aspect by its discourse function (a completed event, an ongoing process, a repeated action), never by mapping English tenses.

Preserve paragraphs, verse lines, dialogue attribution, speaker labels, headings, placeholders, inline code, markup, mathematical notation, and other structural elements. Apply normal Polish punctuation and typography, including „…” quotation marks. Correct only unmistakable mechanical OCR artifacts; never silently alter names, facts, historical spelling, dialect, or deliberate nonstandard usage.

Return the translation only, without a heading, quotation wrapper, notes, alternatives, or commentary.

English source:
<source_text>
{english_text}
</source_text>"""

POLISH_PL_TO_ENG_PROMPT = """You are a senior Polish-to-English translator experienced in literary and specialist nonfiction.

Translate the source accurately and idiomatically. Preserve meaning, agency, logical relations, quantifiers, modality, stance, register, historical distance, voice, imagery, ambiguity, rhetorical devices, and deliberate syntactic pressure. Do not add, omit, summarize, intensify, soften, or modernize the source.

Choose English tense and aspect according to their discourse function. Polish aspect marks a completed event, an ongoing process, or a repeated action; do not apply a fixed perfective-to-simple-past or imperfective-to-progressive rule. Supply English articles from context, and do not read ten or jakiś as a fixed "the" or "a". Recover the subject pronouns Polish omits from verb endings and context, and keep the distance that ty or Pan/Pani expresses. Translate idioms by function while retaining salient imagery. Use established English terminology for Polish institutions when available, and retain the Polish term or proper name when no natural equivalent exists.

Preserve paragraphs, verse lines, speaker labels, stage directions, headings, placeholders, inline code, markup, mathematical notation, numbers, dates, and other structural elements. Apply normal English punctuation and typography. Correct only unmistakable mechanical OCR artifacts; never silently alter names, facts, historical spelling, dialect, or deliberate nonstandard usage.

Return the translation only, without a heading, quotation wrapper, notes, alternatives, or commentary.

Polish source:
<source_text>
{polish_text}
</source_text>"""

POLISH_AUTO_TRANSLATOR_PROMPT = """
You are an expert bilingual assistant for English and Polish.

STEP 1 — Detect the source language:
Examine the input text for linguistic signals.
• Polish signals: Polish letters (ą ć ę ł ń ó ś ź ż), letter groups such as sz, cz, rz, dz, szcz, Polish function words (w, z, na, nie, się, jest, że, od, jak, ale, czy, już, dla, przez, który), Polish inflectional endings.
• English signals: English function words (the, is, are, was, were, have, has, do, does, not, and, but, for, with, this, that, it, I, we, they), English spelling patterns.
When function-word signals are absent, use spelling, letter groups, endings, and Polish letters as evidence. For a genuinely ambiguous word, name, abbreviation, headline, or fragment, do not guess; classify it as ambiguous.

STEP 2 — When the direction is known, translate into the opposite language accurately and idiomatically. Preserve meaning, agency, logical relations, quantifiers, modality, stance, register, historical distance, voice, imagery, ambiguity, and structural formatting. Translate idioms by function, but do not broadly domesticate cultural references or institutions. Preserve proper names and established specialist terminology. Choose tense and aspect by discourse function rather than a fixed grammatical mapping. Into Polish, infer ty or Pan/Pani and the gender of a speaker or addressee only from evidence in the source, and do not render English articles mechanically with ten or jakiś. Correct only unmistakable mechanical OCR artifacts; never alter names, facts, historical spelling, dialect, or deliberate nonstandard usage. Apply normal target-language punctuation and typography, including „…” quotation marks in Polish, while preserving paragraphs, verse lines, speaker labels, stage directions, headings, placeholders, inline code, markup, and mathematical notation.

When the direction is ambiguous, do not translate and write "none" in the Translation field.

No preamble, no extra text before the template. Respond EXACTLY with:

Direction: <english_to_polish|polish_to_english|ambiguous>
Translation:
<translation text preserving structural formatting, or "none" when ambiguous>

Notes:
<when ambiguous, briefly ask the user to choose a direction; otherwise write "none">

Input data:
<source_text>
{source_text}
</source_text>
""".strip()


POLISH_CONFIG = LanguageConfig(
    code="pl",
    display_name="Polish",
    prompt_template=POLISH_PROMPT_TEMPLATE,
    vocab_filename="PolishVocab.tex",
    eng_to_target_filename="EnglishToPolish.tex",
    target_to_eng_filename="PolishToEnglish.tex",
    # Every label is built from display_name and the translator labels.
    ui_strings={},
    input_validator=_validate_polish_text,
    eng_to_target=TranslatorConfig(
        default_filename="EnglishToPolish.tex",
        initial_tex_content=translation_document("engpl", "EN", "PL"),
        final_tex_content=TRANSLATION_DOCUMENT_END,
        prompt_template=POLISH_ENG_TO_PL_PROMPT,
        prompt_variable="english_text",
        source_label="English",
        target_label="Polish",
        ui_title="English → Polish Translator",
        table_headers=("English", "Polish"),
        latex_commands=("engpl",),
    ),
    target_to_eng=TranslatorConfig(
        default_filename="PolishToEnglish.tex",
        initial_tex_content=translation_document("pleng", "PL", "EN"),
        final_tex_content=TRANSLATION_DOCUMENT_END,
        prompt_template=POLISH_PL_TO_ENG_PROMPT,
        prompt_variable="polish_text",
        source_label="Polish",
        target_label="English",
        ui_title="Polish → English Translator",
        table_headers=("Polish", "English"),
        latex_commands=("pleng",),
    ),
    vocab=VocabTemplate(
        initial_content=vocab_document("polish,english", "Przykłady"),
        sample_entry="",
        final_content=VOCAB_DOCUMENT_END,
        entry_command="\\entry",
    ),
    anki=AnkiConfig(
        deck_namespace="PolishDeck",
        default_deck_name="Polish Vocabulary",
        model_seed="PolishVocabModel/v1",
        model_name="Polish Vocab Model v1",
        field_names=("Polish", "Type", "English", "Example"),
        card_templates=bilingual_card_templates("Polish"),
        card_css=get_anki_css("pl"),
    ),
    headword_key=polish_headword_key,
    composition=composition_config(
        "Polish",
        "a beginner (A2) learner writing about everyday life",
        alternative="simple",
    ),
    aliases=("pl-pl", "polish", "polski"),
    auto_prompt_template=POLISH_AUTO_TRANSLATOR_PROMPT,
    auto_prompt_variable="source_text",
    auto_direction_tokens=("english_to_polish", "polish_to_english"),
)


__all__ = ["POLISH_CONFIG", "polish_headword_key"]
