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

AI_PROMPT_TEMPLATE = f"""
        Please provide information for the French word or expression "{{word}}" in the following format, do note, if a user enters an English word or an expression, you are translate it into French to the best of your ability and then do the following. Furthermore if the user were to enter a verb, YOU ARE TO automatically conjugate it into standard infinitive form:
        Correctly Spelt Word: WORD 
        Word Type: [Specify the word type without any additional symbols or marks. Choose from: noun, verb, adjective, expression, adverb, pronominal verb, or use your discretion for other types]
        Definitions:
        a. [First English definition]
        b. [Second English definition]
        c. [Third English definition (if applicable)]
        Examples:
        1. [French example 1]
        [English translation 1]
        2. [French example 2]
        [English translation 2]
        3. [French example 3 (if applicable)]
        [English translation 3 (if applicable)]
Apply the following criteria:
1. Always convert French verbs to their standard infinitive form, regardless of how they're initially conjugated.
2. For the Word Type, use only natural language without any additional symbols or marks.
3. Provide detailed and nuanced English definitions for each entry.
When creating definitions and examples:
- Ensure that the definitions are comprehensive and capture different nuances of the word's meaning.
- Provide context-rich examples that demonstrate the word's usage in various situations.
- Make sure the English translations accurately reflect the meaning and tone of the French examples.
        """