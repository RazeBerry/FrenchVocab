"""Consolidated LaTeX templates for vocabulary and translation documents.

This module contains all LaTeX document templates used by the vocabulary builder:
- Main vocabulary document with definitions and examples
- English→French translation pairs
- French→English translation pairs
"""

# ==============================================================================
# Main Vocabulary LaTeX Templates (detailed word entries with examples)
# ==============================================================================

INITIAL_TEX_CONTENT = r"""\documentclass[11pt]{article}

% ---------- page geometry ----------
\usepackage[a4paper, margin=0.9in]{geometry}

% ---------- encoding & fonts ----------
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{ebgaramond}          % serif body — EB Garamond
\usepackage[scaled=0.88]{sourcesanspro} % sans companion
\usepackage{microtype}            % optical sizing, protrusion, kerning

% ---------- language ----------
\usepackage[french,english]{babel}

% ---------- colour ----------
\usepackage[dvipsnames,svgnames]{xcolor}
\definecolor{headword}{HTML}{1B2A4A}   % dark navy
\definecolor{wordtype}{HTML}{6B6B6B}   % warm gray
\definecolor{exampletrans}{HTML}{3D5A80}% muted steel
% ---------- layout helpers ----------
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage[hidelinks]{hyperref}

% ---------- header / footer ----------
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\fancyfoot[C]{\sffamily\small\textcolor{wordtype}{\thepage}}
\fancypagestyle{plain}{\pagestyle{fancy}}

% ---------- entry command  \entry{word}{type}{defs}{examples} ----------
\newcommand{\entry}[4]{%
  \item[]%
  {\sffamily\large\bfseries\color{headword}\scshape #1}%
  \hspace{0.5em}%
  {\sffamily\small\itshape\color{wordtype}#2}\par\vspace{2pt}%
  \begin{enumerate}[label=\color{headword}\arabic*.,
                    leftmargin=1.4em, topsep=2pt, itemsep=1pt]
    #3
  \end{enumerate}
  \vspace{3pt}%
  {\sffamily\small\bfseries\color{headword}Examples}\par\vspace{1pt}%
  \begin{itemize}[label=\color{headword}\textbullet,
                  leftmargin=1.2em, topsep=1pt, itemsep=2pt]
    #4
  \end{itemize}
  \vspace{0.6cm}%
}

\begin{document}
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

INITIAL_ENG_FR_TEX_CONTENT = r"""\documentclass[11pt]{article}

% ---------- page geometry ----------
\usepackage[a4paper, margin=0.9in]{geometry}

% ---------- encoding & fonts ----------
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{ebgaramond}
\usepackage[scaled=0.88]{sourcesanspro}
\usepackage{microtype}

% ---------- colour ----------
\usepackage[dvipsnames,svgnames]{xcolor}
\definecolor{headword}{HTML}{1B2A4A}
\definecolor{wordtype}{HTML}{6B6B6B}
% ---------- layout ----------
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage[hidelinks]{hyperref}

% ---------- header / footer ----------
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\fancyfoot[C]{\sffamily\small\textcolor{wordtype}{\thepage}}
\fancypagestyle{plain}{\pagestyle{fancy}}

% ---------- translation pair command ----------
% Usage: \engfre{English Text}{French Translation}
\newcommand{\engfre}[2]{%
  \item[]%
  {\sffamily\small\bfseries\color{headword}EN}\enspace #1\\[2pt]%
  {\sffamily\small\bfseries\color{headword}FR}\enspace #2%
  \vspace{0.6em}%
}

\begin{document}

\begin{itemize}[leftmargin=*, itemsep=1ex]
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

INITIAL_FR_ENG_TEX_CONTENT = r"""\documentclass[11pt]{article}

% ---------- page geometry ----------
\usepackage[a4paper, margin=0.9in]{geometry}

% ---------- encoding & fonts ----------
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{ebgaramond}
\usepackage[scaled=0.88]{sourcesanspro}
\usepackage{microtype}

% ---------- colour ----------
\usepackage[dvipsnames,svgnames]{xcolor}
\definecolor{headword}{HTML}{1B2A4A}
\definecolor{wordtype}{HTML}{6B6B6B}
% ---------- layout ----------
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage[hidelinks]{hyperref}

% ---------- header / footer ----------
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\fancyfoot[C]{\sffamily\small\textcolor{wordtype}{\thepage}}
\fancypagestyle{plain}{\pagestyle{fancy}}

% ---------- translation pair command ----------
% Usage: \freeng{French Text}{English Translation}
\newcommand{\freeng}[2]{%
  \item[]%
  {\sffamily\small\bfseries\color{headword}FR}\enspace #1\\[2pt]%
  {\sffamily\small\bfseries\color{headword}EN}\enspace #2%
  \vspace{0.6em}%
}

\begin{document}

\begin{itemize}[leftmargin=*, itemsep=1ex]
% Entries will be added here by the script
"""

FINAL_FR_ENG_TEX_CONTENT = r"""
\end{itemize} % End the list
\end{document}
"""

FR_TO_ENG_TRANSLATION_PROMPT_TEMPLATE = """Translate the following French text accurately and naturally into English. Provide only the English translation, without any introductory phrases, explanations, or quotation marks.

French: "{french_text}"

English Translation:"""
