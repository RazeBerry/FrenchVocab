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
from eng_to_fr_latex_templates import (
    INITIAL_ENG_FR_TEX_CONTENT,
    FINAL_ENG_FR_TEX_CONTENT,
)
from fr_to_eng_latex_templates import (
    INITIAL_FR_ENG_TEX_CONTENT,
    FINAL_FR_ENG_TEX_CONTENT,
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

GERMAN_INITIAL_TEX_CONTENT = r"""\documentclass[12pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[ngerman,english]{babel}
\usepackage{enumitem}
\newcommand{\entry}[4]{
  \item \textbf{#1} (#2)
    \begin{enumerate}[label=\alph*., leftmargin=*]
      #3
    \end{enumerate}
    \textbf{Examples:}
    \begin{itemize}
      #4
    \end{itemize}
  \vspace{0.5cm}
}
\title{Detailed German Vocabulary List}
\author{}
\date{}
\begin{document}
\maketitle
\begin{itemize}[leftmargin=*]"""

GERMAN_FINAL_TEX_CONTENT = r"""
\end{itemize}
\end{document}"""

GERMAN_ENG_TO_DE_PROMPT = """Translate the following English text accurately and naturally into German. Provide only the German translation, without any introductory phrases, explanations, or quotation marks.

English Text: "{english_text}"

German Translation:"""

GERMAN_DE_TO_ENG_PROMPT = """Translate the following German text accurately and naturally into English. Provide only the English translation, without any introductory phrases, explanations, or quotation marks.

German: "{french_text}"

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
        initial_tex_content=INITIAL_ENG_FR_TEX_CONTENT,
        final_tex_content=FINAL_ENG_FR_TEX_CONTENT,
        prompt_template=GERMAN_ENG_TO_DE_PROMPT,
        source_label="English",
        target_label="German",
        ui_title="English → German Translator",
        table_headers=("English", "German"),
    ),
    target_to_eng=TranslatorConfig(
        default_filename="GermanToEnglish.tex",
        initial_tex_content=INITIAL_FR_ENG_TEX_CONTENT,
        final_tex_content=FINAL_FR_ENG_TEX_CONTENT,
        prompt_template=GERMAN_DE_TO_ENG_PROMPT,
        source_label="German",
        target_label="English",
        ui_title="German → English Translator",
        table_headers=("German", "English"),
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
