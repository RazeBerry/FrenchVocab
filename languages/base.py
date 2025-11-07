from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence, Tuple

InputValidator = Callable[[str, bool], bool]


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
    version_id: str | None = None


@dataclass(frozen=True)
class LanguageConfig:
    """Configuration contract describing language-specific behaviour."""

    code: str
    display_name: str
    prompt_template: str
    vocab_filename: str
    eng_to_target_filename: str
    target_to_eng_filename: str
    latex_babel_languages: Sequence[str]
    ui_strings: Mapping[str, str]
    input_validator: InputValidator
    eng_to_target: TranslatorConfig
    target_to_eng: TranslatorConfig
    vocab: VocabTemplate
    anki: AnkiConfig
    aliases: Tuple[str, ...] = ()
    auto_prompt_template: str | None = None
    auto_prompt_variable: str = "source_text"
    auto_direction_tokens: Tuple[str, str] | None = None


__all__ = [
    "LanguageConfig",
    "TranslatorConfig",
    "VocabTemplate",
    "AnkiConfig",
    "AnkiCardTemplate",
    "InputValidator",
]
