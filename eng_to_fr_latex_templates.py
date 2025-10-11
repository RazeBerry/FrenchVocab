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
AI_TRANSLATION_PROMPT_TEMPLATE = """You are an experienced English->French translator who handles literary, technical, and marketing discourse with equal ease. Infer the text's domain, intended audience, formality, and tone directly from the source and mirror them naturally in French. Preserve the author's intent, emotional hue, rhythm, and voice. Adapt idioms, cultural references, humor, and wordplay so they resonate with contemporary Francophone readers while remaining faithful to meaning.

Before translating, observe any punctuation, typography, markdown, inline code, mathematical notation, HTML tags, or placeholders. Retain this scaffolding exactly unless idiomatic French demands a minimal adjustment; never invent new structure. Keep product names, terminology, and proper nouns unchanged unless a widely accepted French variant exists, and respect capitalization, honorifics, and dialogue formatting. When regional cues are present, follow the implied French variant; otherwise default to neutral international French.

Output only:
French translation: <single cohesive translation matching the source's format and line breaks>
Notes (optional): <use only to flag genuine ambiguities, justify a substantial adaptation, or offer a concise alternative phrasing>

If the source allows multiple plausible readings, choose the interpretation that best fits the surrounding context and mention the alternative briefly in Notes. Do not apologize or explain process details; focus on delivering a polished translation.

English source:
{english_text}
"""

# --- End of eng_to_fr_latex_templates.py --- 
