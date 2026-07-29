from __future__ import annotations

from typing import Dict

from .anki_shared_styles import compute_template_hash, get_anki_css
from .base import (
    AnkiCardTemplate,
    AnkiConfig,
    CompositionConfig,
    LanguageConfig,
    VocabTemplate,
    make_text_validator,
)
from .english_tex import ENGLISH_FINAL_TEX_CONTENT, ENGLISH_INITIAL_TEX_CONTENT

_validate_english_text = make_text_validator()

_UI_STRINGS: Dict[str, str] = {
    "app.title": "English Vocabulary Builder",
    "app.panel_title": "English Vocab Helper",
    "menu.add_word": "Add English word or expression",
    "menu.display_all": "Display all English words",
    "menu.anki_export": "Export English words to Anki",
    "menu.anki_reconcile": "Reconcile English Anki exports",
}

ENGLISH_PROMPT_TEMPLATE = """
You are a precise, friendly lexicographer helping a fluent native English speaker learn uncommon English vocabulary. Produce structured plain text for automatic parsing. Never invent a separate sense merely to fill a slot; use nuance, register, contrast, or usage guidance instead.

Input: "{input_text}"
Detected Input Type: {detected_type}  # one of: word | expression | sentence

Internally determine the canonical spelling, the sense most likely intended without additional context, how common or marked the item is, and what a fluent speaker needs in order to recognize and use it naturally. Prefer current, attested usage. If the item is highly specialized, archaic, regional, offensive, or often confused with another word, say so concisely.

Output exactly the following sections, in this order, with these labels. Do not include any extra sections or commentary.

Spelling Check: Write "OK" if spelling is correct; otherwise give a brief correction rationale.
Correctly Spelt Word:
- If Detected Input Type = sentence: reproduce the input exactly, preserving punctuation and case.
- If word or expression: give the canonical headword or fixed expression.
Word Type:
- If Detected Input Type = sentence: sentence
- Otherwise choose exactly one: noun, verb, adjective, adverb, expression, interjection, preposition, conjunction

Definitions:
a. Give the core meaning in direct, familiar English. For a sentence, give a clear plain-English paraphrase.
b. Explain connotation, register, rarity, domain, or the most important secondary sense. For a sentence, explain its key nuance or subtext.
c. Give a useful contrast, common collocation, usage trap, or genuinely distinct sense. Do not fabricate a third sense. For a sentence, give an alternative natural phrasing.

Examples:
Provide exactly three examples numbered "1.", "2.", "3.".
- For a word or expression, write a natural English sentence that makes the meaning recoverable from context.
- For a sentence, write a natural English variant with the same intent.
- Vary register and context when the item permits it; demonstrate any important grammar or collocation.

Formatting rules for every example:
1. First line: the English example containing the headword, an ordinary inflection, or the sentence variant.
2. Next line: a familiar plain-English paraphrase in parentheses, avoiding the headword when practical.

Do not use square brackets. Do not include LaTeX. Use only plain text. Start with "Spelling Check:" and end immediately after the closing parenthesis of the third paraphrase. Definitions must begin with exactly "a. ", "b. ", and "c. "; examples must begin with exactly "1. ", "2. ", and "3. ".
""".strip()

ENGLISH_COMPOSITION_GRADING_PROMPT = """
You are a rigorous but practical English usage coach for a fluent native speaker learning uncommon vocabulary.

Grade one short English composition. The learner was asked to use the target words below. Judge whether each word is used with the correct meaning, grammar, collocation, connotation, and register. Penalize writing that is technically possible but conspicuously unnatural or needlessly grandiose. Give a reason for every correction and one strong alternative phrasing.

Target words:
{target_words}

Vocabulary details from the learner's own list:
{word_details}

Learner attempt:
{user_text}

Respond in plain text with exactly these section headers. Do not add any other headers.

Corrected Text:
<full corrected English attempt>

English Gloss:
<a plain-English paraphrase of the corrected attempt, avoiding the target words when practical>

Corrections:
1. "<learner wording>" -> "<corrected wording>"
   Why: <brief reason>
   Alternative: <strong idiomatic alternative>

Word Verdicts:
- <target word>: <correct|incorrect|not_used>

Unknown Word Candidates:
- <uncommon English word not already in the target list>: <plain-English gloss>

Register: <consistent|mixed|too informal|too formal, with a brief note if useful>

If there are no corrections or unknown candidates, write "none" in that section. Keep the feedback concise and concrete.
""".strip()

ENGLISH_RECALL_GRADING_PROMPT = """
You are a rigorous but practical English usage coach for a fluent native speaker learning uncommon vocabulary.

The learner saw a plain-English cue and was asked to write an idiomatic English sentence using the target word. Compare the attempt with the stored example, but accept any natural sentence that expresses the cue's intended sense; the stored example is not the only acceptable answer. The target word, or an ordinary inflected form of it, must be used correctly. Give a reason for every correction and one strong alternative phrasing.

Target word:
{target_word}

Vocabulary details from the learner's own list:
{word_details}

Plain-English cue shown to the learner:
{source_english}

Stored English example:
{reference_target}

Learner attempt:
{user_text}

Respond in plain text with exactly these section headers. Do not add any other headers.

Corrected Text:
<full corrected English attempt>

Corrections:
1. "<learner wording>" -> "<corrected wording>"
   Why: <brief reason>
   Alternative: <strong idiomatic alternative>

Word Verdicts:
- <target word>: <correct|incorrect|not_used>

Unknown Word Candidates:
- <uncommon English word not already in the target list>: <plain-English gloss>

Register: <consistent|mixed|too informal|too formal, with a brief note if useful>

If there are no corrections or unknown candidates, write "none" in that section. Keep the feedback concise and concrete.
""".strip()

_CARD_FRONT_TEMPLATE = """
<div class="entry-card entry-card--front">
  <div class="entry-header">
    <div class="entry-word">{{Word}}</div>
    {{#Type}}<div class="entry-pos">{{Type}}</div>{{/Type}}
  </div>
</div>
""".strip()

_CARD_BACK_TEMPLATE = """
<div class="entry-card entry-card--back">
  <div class="entry-header">
    <div class="entry-word">{{Word}}</div>
    {{#Type}}<div class="entry-pos">{{Type}}</div>{{/Type}}
  </div>
  {{#Definitions}}
  <div class="entry-section">
    <div class="entry-section-title">Definitions and usage</div>
    <div class="entry-content">{{Definitions}}</div>
  </div>
  {{/Definitions}}
  {{#Examples}}
  <div class="entry-section">
    <div class="entry-section-title">Examples</div>
    <div class="entry-content">{{Examples}}</div>
  </div>
  {{/Examples}}
</div>
""".strip()

ENGLISH_CARD_TEMPLATES = (
    AnkiCardTemplate(
        name="Recognition",
        question_format=_CARD_FRONT_TEMPLATE,
        answer_format=_CARD_BACK_TEMPLATE,
    ),
)
ENGLISH_CARD_CSS = get_anki_css("en")
ENGLISH_CARD_VERSION = compute_template_hash(
    [
        {"name": template.name, "qfmt": template.question_format, "afmt": template.answer_format}
        for template in ENGLISH_CARD_TEMPLATES
    ],
    ENGLISH_CARD_CSS,
)

ENGLISH_CONFIG = LanguageConfig(
    code="en",
    display_name="English",
    prompt_template=ENGLISH_PROMPT_TEMPLATE,
    vocab_filename="EnglishVocab.tex",
    eng_to_target_filename=None,
    target_to_eng_filename=None,
    latex_babel_languages=("english",),
    ui_strings=_UI_STRINGS,
    input_validator=_validate_english_text,
    eng_to_target=None,
    target_to_eng=None,
    vocab=VocabTemplate(
        initial_content=ENGLISH_INITIAL_TEX_CONTENT,
        sample_entry="",
        final_content=ENGLISH_FINAL_TEX_CONTENT,
        entry_command="\\entry",
    ),
    anki=AnkiConfig(
        deck_namespace="EnglishDeck",
        default_deck_name="English Vocabulary",
        model_seed="EnglishVocabModel/v1",
        model_name="English Vocab Model v1",
        field_names=("Word", "Type", "Definitions", "Examples"),
        card_templates=ENGLISH_CARD_TEMPLATES,
        card_css=ENGLISH_CARD_CSS,
        version_id=ENGLISH_CARD_VERSION,
    ),
    composition=CompositionConfig(
        grading_prompt_template=ENGLISH_COMPOSITION_GRADING_PROMPT,
        reverse_grading_prompt_template=ENGLISH_RECALL_GRADING_PROMPT,
        ui_title="English Usage Practice",
        use_words_label="Daily set (use these words)",
        reverse_label="Recall from a plain-English cue",
        reverse_source_label="Plain-English cue",
        reverse_instruction_template=(
            'Write an idiomatic English sentence using "{target_word}".'
        ),
        input_instruction_template="Write 1-4 sentences in English.",
    ),
    aliases=("english", "en-us", "en-gb"),
    learning_mode="monolingual",
)


__all__ = ["ENGLISH_CONFIG"]
