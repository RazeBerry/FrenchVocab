from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from string import Template
from typing import Callable, FrozenSet, Literal, Mapping, Sequence, Tuple

InputValidator = Callable[[str, bool], bool]
LearningMode = Literal["bilingual", "monolingual"]

# Base punctuation set shared across all languages.
#
# Note: we accept common typographic apostrophes/hyphens because many systems
# auto-substitute them (e.g., today’s → today\u2019s, non‑breaking hyphen).
_BASE_VALID_CHARS: FrozenSet[str] = frozenset(
    {
        "-",  # hyphen-minus
        "‐",  # hyphen
        "‑",  # non-breaking hyphen
        "'",  # apostrophe
        "’",  # right single quotation mark
        "‘",  # left single quotation mark
        "ʼ",  # modifier letter apostrophe
    }
)

_SENTENCE_VALID_CHARS: FrozenSet[str] = frozenset(
    {
        *_BASE_VALID_CHARS,
        "–",  # en dash
        "—",  # em dash
        ",",
        ".",
        ";",
        ":",
        "!",
        "?",
        "(",
        ")",
        "[",
        "]",
        '"',
        "“",
        "”",
        "«",
        "»",
        "…",
        "/",
        "\\",
        "%",
        "$",
        "€",
        "#",
        "&",
        "+",
        "*",
        "@",
        "=",
    }
)


def make_text_validator(extra_chars: FrozenSet[str] = frozenset()) -> InputValidator:
    """Create a text validator with optional language-specific characters.

    Args:
        extra_chars: Additional valid characters for this language (e.g., German quotes)

    Returns:
        A validation function compatible with InputValidator signature
    """
    sentence_chars = _SENTENCE_VALID_CHARS | extra_chars

    def validator(text: str, allow_sentences: bool) -> bool:
        stripped = text.strip()
        if not stripped:
            return False

        if not allow_sentences:
            return all(
                ch.isalpha() or ch.isspace() or ch in _BASE_VALID_CHARS
                for ch in stripped
            )

        return all(
            ch.isalpha() or ch.isspace() or ch.isdigit() or ch in sentence_chars
            for ch in stripped
        )

    return validator


@dataclass(frozen=True)
class TranslatorConfig:
    """Configuration for a single translation workflow."""

    default_filename: str
    initial_tex_content: str
    final_tex_content: str
    prompt_template: str
    prompt_variable: str
    source_label: str
    target_label: str
    ui_title: str
    table_headers: Tuple[str, str]
    latex_commands: Tuple[str, ...]


@dataclass(frozen=True)
class CompositionConfig:
    """Language-specific composition-practice grading configuration."""

    grading_prompt_template: str
    reverse_grading_prompt_template: str = ""
    ui_title: str = "Composition Practice"
    use_words_label: str = "Daily set (use these words)"
    reverse_label: str = "Daily set (reverse translation)"
    reverse_source_label: str = "English source"
    reverse_instruction_template: str = "Translate into {language}."
    input_instruction_template: str = "Write 1-4 sentences in {language}."
    max_sentences: int = 4


# Composition grading for a bilingual language. ``$language`` names the target
# language and ``$learner`` completes "composition coach for <learner>"; the
# brace placeholders are filled per attempt by the composition coach.
_COMPOSITION_GRADING_PROMPT = Template("""
You are a rigorous but warm $language composition coach for $learner.

Grade one short $language composition. The learner was asked to use the target words below. Judge whether each target word is used idiomatically in context, not merely present. Give reasons for every correction and one stronger alternative phrasing. Keep the feedback concise and practical.

Target words:
{target_words}

Vocabulary details from the learner's own list:
{word_details}

Learner attempt:
{user_text}

Respond in plain text with exactly these section headers. Do not add any other headers.

Corrected Text:
<full corrected $language attempt>

English Gloss:
<natural English gloss of the corrected $language attempt>

Corrections:
1. "<learner wording>" -> "<corrected wording>"
   Why: <brief reason>
   Alternative: <stronger idiomatic phrasing>

Word Verdicts:
- <target word>: <correct|incorrect|not_used>

Unknown Word Candidates:
- <$language word not already in the target list>: <English gloss>

Register: <consistent|mixed|too informal|too formal, with a short note if needed>

If there are no corrections or unknown candidates, write "none" in that section. Preserve a coach-with-reasons voice.
""".strip())

_REVERSE_COMPOSITION_GRADING_PROMPT = Template("""
You are a rigorous but warm $language composition coach for $learner.

Grade one short $language reverse-translation attempt. The learner saw an English sentence from their own vocabulary example and translated it into $language. Compare the attempt with the stored $language reference, but accept exact matches and idiomatic equivalent variants; the stored reference is not the only acceptable answer. Judge whether the sampled target word is produced idiomatically in context, including natural inflected or closely equivalent forms. Give reasons for every correction and one stronger alternative phrasing. Keep the feedback concise and practical.

Target word:
{target_word}

Vocabulary details from the learner's own list:
{word_details}

English source shown to the learner:
{source_english}

Stored $language reference:
{reference_target}

Learner attempt:
{user_text}

Respond in plain text with exactly these section headers. Do not add any other headers.

Corrected Text:
<full corrected $language attempt>

Corrections:
1. "<learner wording>" -> "<corrected wording>"
   Why: <brief reason>
   Alternative: <stronger idiomatic phrasing>

Word Verdicts:
- <target word>: <correct|incorrect|not_used>

Unknown Word Candidates:
- <$language word not already in the target list>: <English gloss>

Register: <consistent|mixed|too informal|too formal, with a short note if needed>

If there are no corrections or unknown candidates, write "none" in that section. Preserve a coach-with-reasons voice.
""".strip())


def composition_config(language: str, learner: str) -> CompositionConfig:
    """Return composition grading for a bilingual language.

    ``language`` is the display name ("French"). ``learner`` states the
    learner's level and goal, for example "an advanced learner aiming at DALF
    C2 register awareness".
    """
    return CompositionConfig(
        grading_prompt_template=_COMPOSITION_GRADING_PROMPT.substitute(
            language=language, learner=learner
        ),
        reverse_grading_prompt_template=_REVERSE_COMPOSITION_GRADING_PROMPT.substitute(
            language=language, learner=learner
        ),
        ui_title=f"{language} Composition Practice",
    )

@dataclass(frozen=True)
class VocabTemplate:
    """Configuration for the core vocabulary LaTeX document."""

    initial_content: str
    sample_entry: str
    final_content: str
    entry_command: str = "\\entry"


@dataclass(frozen=True)
class AnkiCardTemplate:
    name: str
    question_format: str
    answer_format: str


@dataclass(frozen=True)
class AnkiConfig:
    deck_namespace: str
    default_deck_name: str
    model_seed: str
    model_name: str
    field_names: Sequence[str]
    card_templates: Sequence[AnkiCardTemplate]
    card_css: str = ""
    guid_headword_aliases: Mapping[str, str] = field(default_factory=dict)

    @property
    def version_id(self) -> str:
        """Hash of the card templates and CSS.

        An exported deck records it, and a different value makes the next
        export include every note (core/anki_manager.py).
        """
        payload = {
            "templates": [
                {
                    "name": template.name,
                    "qfmt": template.question_format,
                    "afmt": template.answer_format,
                }
                for template in self.card_templates
            ],
            "css": self.card_css,
        }
        return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LanguageConfig:
    """Configuration contract describing language-specific behaviour."""

    code: str
    display_name: str
    prompt_template: str
    vocab_filename: str
    eng_to_target_filename: str | None
    target_to_eng_filename: str | None
    ui_strings: Mapping[str, str]
    input_validator: InputValidator
    eng_to_target: TranslatorConfig | None
    target_to_eng: TranslatorConfig | None
    vocab: VocabTemplate
    anki: AnkiConfig
    # The headword's identity, alphabetical order and rail letter; the key is
    # opaque and never displayed (docs/vocabulary.md).
    headword_key: Callable[[str], str]
    composition: CompositionConfig | None = None
    aliases: Tuple[str, ...] = ()
    auto_prompt_template: str | None = None
    auto_prompt_variable: str = "source_text"
    auto_direction_tokens: Tuple[str, str] | None = None
    learning_mode: LearningMode = "bilingual"

    @property
    def supports_translation(self) -> bool:
        """Whether this language exposes the bilingual translation workflows."""
        return (
            self.learning_mode == "bilingual"
            and self.eng_to_target is not None
            and self.target_to_eng is not None
        )


__all__ = [
    "LanguageConfig",
    "CompositionConfig",
    "composition_config",
    "TranslatorConfig",
    "VocabTemplate",
    "AnkiConfig",
    "AnkiCardTemplate",
    "InputValidator",
    "LearningMode",
    "make_text_validator",
]
