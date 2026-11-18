"""LaTeX documents written once, when a vocabulary or translation file is created.

Every language shares one vocabulary document and one translation document;
a language supplies only its babel options, examples heading and pair macros.
Existing files are never rewritten from these templates.
"""

from string import Template

_VOCAB_DOCUMENT = Template(r"""\documentclass[11pt]{article}

% ---------- page geometry ----------
\usepackage[a4paper, margin=0.9in]{geometry}

% ---------- encoding & fonts ----------
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{ebgaramond}
\usepackage[scaled=0.88]{sourcesanspro}
\usepackage{microtype}

% ---------- language ----------
\usepackage[$babel]{babel}

% ---------- colour ----------
\usepackage[dvipsnames,svgnames]{xcolor}
\definecolor{headword}{HTML}{1B2A4A}
\definecolor{wordtype}{HTML}{6B6B6B}
\definecolor{exampletrans}{HTML}{3D5A80}
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
  {\sffamily\small\bfseries\color{headword}$examples_heading}\par\vspace{1pt}%
  \begin{itemize}[label=\color{headword}\textbullet,
                  leftmargin=1.2em, topsep=1pt, itemsep=2pt]
    #4
  \end{itemize}
  \vspace{0.6cm}%
}

\begin{document}
\begin{itemize}[leftmargin=*]
\item[]\relax""")

VOCAB_DOCUMENT_END = r"""
\end{itemize}
\end{document}"""

_TRANSLATION_DOCUMENT = Template(r"""\documentclass[11pt]{article}

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
% Usage: \$command{$first_label text}{$second_label text}
\newcommand{\$command}[2]{%
  \item[]%
  {\sffamily\small\bfseries\color{headword}$first_label}\enspace #1\\[2pt]%
  {\sffamily\small\bfseries\color{headword}$second_label}\enspace #2%
  \vspace{0.6em}%
}

\begin{document}

\begin{itemize}[leftmargin=*, itemsep=1ex]
\item[]\relax
""")

TRANSLATION_DOCUMENT_END = r"""
\end{itemize}
\end{document}
"""


def vocab_document(babel: str, examples_heading: str) -> str:
    """Return the opening of a new vocabulary file.

    ``babel`` is the babel option list ("french,english"); ``examples_heading``
    titles each entry's examples. Close the file with ``VOCAB_DOCUMENT_END``.
    """
    return _VOCAB_DOCUMENT.substitute(babel=babel, examples_heading=examples_heading)


def translation_document(command: str, first_label: str, second_label: str) -> str:
    """Return the opening of a new translation file.

    ``command`` names the pair macro (``engfre``) whose two arguments are
    labelled ``first_label`` and ``second_label`` ("EN", "FR"). Close the file
    with ``TRANSLATION_DOCUMENT_END``.
    """
    return _TRANSLATION_DOCUMENT.substitute(
        command=command, first_label=first_label, second_label=second_label
    )


__all__ = [
    "TRANSLATION_DOCUMENT_END",
    "VOCAB_DOCUMENT_END",
    "translation_document",
    "vocab_document",
]
