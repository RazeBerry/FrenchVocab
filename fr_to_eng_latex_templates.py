# fr_to_eng_latex_templates.py

# This constant defines the basic structure of the new FrenchToEnglish.tex file.
# It includes necessary LaTeX setup and defines our custom command \\freeng.
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

# This constant defines the very end of the LaTeX document.
FINAL_FR_ENG_TEX_CONTENT = r"""
\end{itemize} % End the list
\end{document}
"""

# This is the template for the prompt we send to the AI.
# We ask it specifically to translate the given French text to English
# and provide *only* the translation to keep the response clean.
FR_TO_ENG_TRANSLATION_PROMPT_TEMPLATE = """Translate the following French text accurately and naturally into English. Provide only the English translation, without any introductory phrases, explanations, or quotation marks.

French: "{french_text}"

English Translation:"""

# --- End of fr_to_eng_latex_templates.py --- 