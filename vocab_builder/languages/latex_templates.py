"""Consolidated LaTeX templates for vocabulary and translation documents.

This module contains all LaTeX document templates used by the vocabulary builder:
- Main vocabulary document with definitions and examples
- English→French translation pairs
- French→English translation pairs
"""

# ==============================================================================
# Main Vocabulary LaTeX Templates (detailed word entries with examples)
# ==============================================================================

INITIAL_TEX_CONTENT = r"""\documentclass[12pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[french,english]{babel}
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
\title{Detailed French Vocabulary List}
\author{}
\date{}
\begin{document}
\maketitle
\begin{itemize}[leftmargin=*]"""

SAMPLE_ENTRY = r"""\entry{agaçante}{Unknown}
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

FINAL_TEX_CONTENT = r"""
\end{itemize}
\end{document}"""


# ==============================================================================
# English → French Translation Templates
# ==============================================================================

INITIAL_ENG_FR_TEX_CONTENT = r"""\documentclass[12pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{geometry}
\geometry{a4paper, margin=1in}
\usepackage{enumitem} % For itemize customization if needed later

\title{English to French Translations}
\author{Vocabulary Builder Tool}
\date{\today}

% Define a simple command to display English and French pairs
% Usage: \engfre{English Text}{French Translation}
\newcommand{\engfre}[2]{%
  \item \textbf{EN:} #1 \\ \textbf{FR:} #2% Add a newline between pairs
  \vspace{0.5em} % Add a little vertical space between entries
}

\begin{document}
\maketitle

\section*{Saved Translations}

\begin{itemize}[leftmargin=*, itemsep=1ex] % Start a list for the entries
% Entries will be added here by the script
"""

FINAL_ENG_FR_TEX_CONTENT = r"""
\end{itemize} % End the list
\end{document}
"""

AI_TRANSLATION_PROMPT_TEMPLATE = """You are an experienced English->French translator who handles literary, technical, and marketing discourse with equal ease. Infer the text's domain, intended audience, formality, and tone directly from the source and mirror them naturally in French. Preserve the author's intent, emotional hue, rhythm, and voice. Adapt idioms, cultural references, humor, and wordplay so they resonate with contemporary Francophone readers while remaining faithful to meaning.

Before translating, observe any punctuation, typography, markdown, inline code, mathematical notation, HTML tags, or placeholders. Retain this scaffolding exactly unless idiomatic French demands a minimal adjustment; never invent new structure. Keep product names, terminology, and proper nouns unchanged unless a widely accepted French variant exists, and respect capitalization, honorifics, and dialogue formatting. When regional cues are present, follow the implied French variant; otherwise default to neutral international French.

Output only:
French translation: <single cohesive translation matching the source's format and line breaks>
Notes (optional): <use only to flag genuine ambiguities, justify a substantial adaptation, or offer a concise alternative phrasing>

If the source allows multiple plausible readings, choose the interpretation that best fits the surrounding context and mention the alternative briefly in Notes. Do not apologize or explain process details; focus on delivering a polished translation.

English source:
{english_text}
"""


# ==============================================================================
# French → English Translation Templates
# ==============================================================================

INITIAL_FR_ENG_TEX_CONTENT = r"""\documentclass[12pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{geometry}
\geometry{a4paper, margin=1in}
\usepackage{enumitem} % For itemize customization if needed later

\title{French to English Translations}
\author{Vocabulary Builder Tool}
\date{\today}

% Define a simple command to display French and English pairs
% Usage: \freeng{French Text}{English Translation}
\newcommand{\freeng}[2]{%
  \item \textbf{FR:} #1 \\ \textbf{EN:} #2%
  \vspace{0.5em} % Add a little vertical space between entries
}

\begin{document}
\maketitle

\section*{Saved Translations}

\begin{itemize}[leftmargin=*, itemsep=1ex] % Start a list for the entries
% Entries will be added here by the script
"""

FINAL_FR_ENG_TEX_CONTENT = r"""
\end{itemize} % End the list
\end{document}
"""

FR_TO_ENG_TRANSLATION_PROMPT_TEMPLATE = """Translate the following French text accurately and naturally into English. Provide only the English translation, without any introductory phrases, explanations, or quotation marks.

French: "{french_text}"

English Translation:"""
