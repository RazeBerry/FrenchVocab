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

# --- UNIFIED AI PROMPT TEMPLATE (word, expression, or sentence) ---
AI_PROMPT_TEMPLATE = """
You are a friendly and highly experienced DALF C1/C2 French instructor. Produce structured output for automatic parsing.

Input: "{input_text}"
Detected Input Type: {detected_type}  # one of: word | expression | sentence

Output exactly the following sections, in this order, with these labels. Do not include any extra sections or commentary.

Spelling Check: Write "OK" if spelling is correct, otherwise briefly note the correction rationale.
Correctly Spelt Word:
- If Detected Input Type = sentence: output the input EXACTLY (preserve punctuation, quotes, dashes, case). No lemmatization, no rephrasing, no synonyms.
- If word/expression: provide the canonical base form (verb infinitive, noun singular, or fixed expression).
Word Type:
- If Detected Input Type = sentence: sentence
- Else: one of noun, verb, adjective, adverb, pronominal verb, expression (choose exactly one)

Definitions:
a. If sentence: the best natural English translation of the whole sentence. Otherwise: the primary English gloss with brief nuance if helpful.
b. If sentence: one brief note (register, nuance, key structure). Otherwise: a second distinct sense (or usage note) if applicable.
c. If sentence: one alternative natural English phrasing. Otherwise: a third distinct sense only if truly distinct.

Examples:
Provide exactly three examples numbered "1.", "2.", "3.".
- If verb/expression: use Present for 1, Past (Passé Composé or Imparfait) for 2, Future Simple for 3.
- If noun/adjective/adverb: choose varied, natural contexts (no tense constraint).
- If sentence: provide three French paraphrases/variants of the original sentence (keep meaning), each with its English translation.

Formatting rules for every example:
1. First line: the French sentence.
2. Next line: the English translation in parentheses, on its own line.

Do not use square brackets anywhere. Do not include LaTeX. Use only plain text. Start with "Spelling Check:" and end right after the closing parenthesis of the third example's translation. Ensure Definitions entries start with exactly "a. ", "b. ", "c. " and Examples with exactly "1. ", "2. ", "3. ".

Examples of acceptable "Word Type" selection:
- "manger" → verb
- "avoir faim" → expression
- "Il pleuvra demain." → sentence

Notes:
- Prefer the most common senses; keep each definition concise.
- Preserve proper nouns; correct only obvious typos.
- If any conflict between detected type and your inference, prefer “sentence” when the input is long, has sentence punctuation, or contains newlines.
- Use standard modern French; neutral register unless context requires otherwise.
"""
