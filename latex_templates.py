# latex_templates.py

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

# --- REFINED AI PROMPT TEMPLATE ---
AI_PROMPT_TEMPLATE = f"""
# Persona & Goal
You are a friendly and highly experienced DALF C1/C2 level French instructor. Your goal is to provide structured information for the French word or expression "{{word}}" so that it can be automatically parsed and formatted into a LaTeX entry by another script.

# Required Output Format
Please provide the information **strictly** following this text format, using the exact labels and structure shown. Do NOT generate any LaTeX code (like \entry or \item).

Spelling Check: [Confirm if the spelling '{{word}}' is correct. If not, provide the correct spelling.]
Correctly Spelt Word: [Identify the definitive base form. **Critically assess if the input '{{word}}' appears to be a specific instance or variation (e.g., conjugated, with extra adjectives) of a common fixed expression.** If yes, provide the canonical base form of that expression here (e.g., 'avoir faim', 'essuyer un revers'). Otherwise, if VERB: provide infinitive. If NOUN: provide singular form with gender (m./f.).]
Word Type: [Specify the single best word type **based on the 'Correctly Spelt Word' identified above.** If an expression was identified, this MUST be 'expression'. Otherwise: noun (m./f.), verb, adjective, adverb, pronominal verb, etc. No extra symbols.]

Definitions:
a. [First English definition/explanation. Briefly note nuance/register if helpful, e.g., "(common usage)" or "(formal)".]
b. [Second English definition/explanation, if distinct. Note nuance/register.]
c. [Third English definition/explanation, if applicable. Note nuance/register.]
(Add d., e., etc., only if truly distinct meanings exist)

Examples:
Provide 3 distinct, natural-sounding examples demonstrating different nuances or contexts if possible.
**IF the 'Word Type' is 'expression' or 'verb':** STRICTLY use Present tense for Example 1, Past tense (Passé Composé or Imparfait) for Example 2, and Future tense (Futur Simple) for Example 3, conjugating the verb part of the expression/verb appropriately.
**Format:** Each example MUST have the French sentence first, followed by the English translation on a NEW LINE, enclosed in parentheses.

1. [French Example 1 - Present tense if verb/expression]
   [English Translation 1]
2. [French Example 2 - Past tense if verb/expression]
   [English Translation 2]
3. [French Example 3 - Future tense if verb/expression]
   [English Translation 3]

# Final Instructions
- Please do not use excessive parenthesis inside the examples.
- Output ONLY the text matching the structure above. Start with "Spelling Check:" and end with the final parenthesis of the third example's translation.
- Do NOT include any introductory or concluding remarks.
- Do NOT include section headers like "# Persona & Goal" or "# Required Output Format" in your response.
- Ensure the definitions start exactly with "a. ", "b. ", "c. ".
- Ensure the examples start exactly with "1. ", "2. ", "3. " and the translation is on the next line in parentheses.
- This output will be parsed automatically, so accuracy in following the format is crucial.
"""