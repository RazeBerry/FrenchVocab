# eng_to_fr_latex_templates.py

# This constant defines the basic structure of the new EnglishToFrench.tex file.
# It includes necessary LaTeX setup and defines our custom command \engfre.
INITIAL_ENG_FR_TEX_CONTENT = r"""\\documentclass[12pt]{article}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage{geometry}
\\geometry{a4paper, margin=1in}
\\usepackage{enumitem} % For itemize customization if needed later

\\title{English to French Translations}
\\author{Vocabulary Builder Tool}
\\date{\\today}

% Define a simple command to display English and French pairs
% Usage: \\engfre{English Text}{French Translation}
\\newcommand{\\engfre}[2]{%
  \\item \\textbf{EN:} #1 \\\\ \\textbf{FR:} #2% Add a newline between pairs
  \\vspace{0.5em} % Add a little vertical space between entries
}

\\begin{document}
\\maketitle

\\section*{Saved Translations}

\\begin{itemize}[leftmargin=*, itemsep=1ex] % Start a list for the entries
% Entries will be added here by the script
"""

# This constant defines the very end of the LaTeX document.
FINAL_ENG_FR_TEX_CONTENT = r"""
\\end{itemize} % End the list
\\end{document}
"""

# This is the template for the prompt we send to the Anthropic AI.
# We ask it specifically to translate the given English text to French
# and provide *only* the translation to keep the response clean.
AI_TRANSLATION_PROMPT_TEMPLATE = """Translate the following English text accurately and naturally into French. Provide only the French translation, without any introductory phrases, explanations, or quotation marks.

English: {english_text}

French Translation:"""

# --- End of eng_to_fr_latex_templates.py --- 