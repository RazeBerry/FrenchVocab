"""LaTeX templates dedicated to the German configuration."""

GERMAN_INITIAL_TEX_CONTENT = r"""\\documentclass[12pt]{article}
\\usepackage[margin=1in]{geometry}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage{lmodern}
\\usepackage[ngerman,english]{babel}
\\usepackage{enumitem}
\\newcommand{\\entry}[4]{
  \\item \\textbf{#1} (#2)
    \\begin{enumerate}[label=\\alph*., leftmargin=*]
      #3
    \\end{enumerate}
    \\textbf{Beispiele:}
    \\begin{itemize}
      #4
    \\end{itemize}
  \\vspace{0.5cm}
}
\\title{Ausführlicher deutscher Wortschatz}
\\author{}
\\date{}
\\begin{document}
\\maketitle
\\begin{itemize}[leftmargin=*]"""

GERMAN_FINAL_TEX_CONTENT = r"""
\\end{itemize}
\\end{document}"""

INITIAL_ENG_DE_TEX_CONTENT = r"""\\documentclass[12pt]{article}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage{geometry}
\\geometry{a4paper, margin=1in}
\\usepackage{enumitem}

\\title{English to German Translations}
\\author{Vocabulary Builder Tool}
\\date{\\today}

% Usage: \\engde{English Text}{German Translation}
\\newcommand{\\engde}[2]{%
  \\item \\textbf{EN:} #1 \\\\ \\textbf{DE:} #2
  \\vspace{0.5em}
}

\\begin{document}
\\maketitle

\\section*{Saved Translations}

\\begin{itemize}[leftmargin=*, itemsep=1ex]
"""

FINAL_ENG_DE_TEX_CONTENT = r"""
\\end{itemize}
\\end{document}
"""

INITIAL_DE_ENG_TEX_CONTENT = r"""\\documentclass[12pt]{article}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage{geometry}
\\geometry{a4paper, margin=1in}
\\usepackage{enumitem}

\\title{German to English Translations}
\\author{Vocabulary Builder Tool}
\\date{\\today}

% Usage: \\deeng{German Text}{English Translation}
\\newcommand{\\deeng}[2]{%
  \\item \\textbf{DE:} #1 \\\\ \\textbf{EN:} #2
  \\vspace{0.5em}
}

\\begin{document}
\\maketitle

\\section*{Saved Translations}

\\begin{itemize}[leftmargin=*, itemsep=1ex]
"""

FINAL_DE_ENG_TEX_CONTENT = r"""
\\end{itemize}
\\end{document}
"""
