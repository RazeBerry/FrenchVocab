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
\begin{itemize}[leftmargin=*]
\item[]\relax"""

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
\item[]\relax
"""

FINAL_ENG_FR_TEX_CONTENT = r"""
\end{itemize} % End the list
\end{document}
"""

AI_TRANSLATION_PROMPT_TEMPLATE = """You are a senior English-to-French translator experienced in literary and specialist nonfiction.

Translate the source accurately and idiomatically. Infer its domain, audience, tone, formality, and era, and reproduce them in French. Preserve meaning, agency, logical relations, quantifiers, modality, stance, voice, imagery, ambiguity, rhythm, and historical distance. Do not add, omit, summarize, intensify, soften, or modernize the source.

Translate idioms and wordplay by function when a natural French solution exists. Preserve cultural references, institutions, terminology, and proper names unless an established French equivalent genuinely exists. Infer tu/vous only from evidence in the source; when the relationship is ambiguous, prefer wording that does not invent one.

Preserve paragraphs, verse lines, dialogue attribution, headings, placeholders, inline code, markup, mathematical notation, and other structural elements. Apply normal French punctuation, quotation marks, and spacing. Correct only unmistakable mechanical OCR artifacts; never silently alter names, facts, historical spelling, dialect, or deliberate nonstandard usage.

Return the translation only, without a heading, quotation wrapper, notes, alternatives, or commentary.

English source:
<source_text>
{english_text}
</source_text>"""


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
\item[]\relax
"""

FINAL_FR_ENG_TEX_CONTENT = r"""
\end{itemize} % End the list
\end{document}
"""

FR_TO_ENG_TRANSLATION_PROMPT_TEMPLATE = """You are a senior French-to-English translator experienced in literature and specialist nonfiction.

Translate the source accurately and idiomatically. Preserve meaning, agency, logical relations, quantifiers, modality, stance, register, historical distance, voice, imagery, ambiguity, repetitions, and rhetorical force. Do not add, omit, summarize, intensify, soften, or modernize the source.

Write natural English without mechanically smoothing deliberate syntactic pressure or changing rhetorical tense. Translate idioms by function and use established English equivalents for specialist and cultural terms. Preserve the French term or proper name when no natural established equivalent exists.

Preserve paragraphs, verse lines, speaker labels, stage directions, headings, placeholders, inline code, markup, mathematical notation, and other structural elements. Apply normal English punctuation and typography. Correct only unmistakable mechanical OCR artifacts; never silently alter names, facts, historical spelling, dialect, or deliberate nonstandard usage.

Return the translation only, without a heading, quotation wrapper, notes, alternatives, or commentary.

French source:
<source_text>
{french_text}
</source_text>"""
