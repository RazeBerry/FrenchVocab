"""LaTeX templates dedicated to the German configuration."""

GERMAN_INITIAL_TEX_CONTENT = r"""\\documentclass[11pt]{article}

% ---------- page geometry ----------
\\usepackage[a4paper, margin=0.9in]{geometry}

% ---------- encoding & fonts ----------
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage{ebgaramond}
\\usepackage[scaled=0.88]{sourcesanspro}
\\usepackage{microtype}

% ---------- language ----------
\\usepackage[ngerman,english]{babel}

% ---------- colour ----------
\\usepackage[dvipsnames,svgnames]{xcolor}
\\definecolor{headword}{HTML}{1B2A4A}
\\definecolor{wordtype}{HTML}{6B6B6B}
\\definecolor{exampletrans}{HTML}{3D5A80}
% ---------- layout helpers ----------
\\usepackage{enumitem}
\\usepackage{fancyhdr}
\\usepackage[hidelinks]{hyperref}

% ---------- header / footer ----------
\\pagestyle{fancy}
\\fancyhf{}
\\renewcommand{\\headrulewidth}{0pt}
\\fancyfoot[C]{\\sffamily\\small\\textcolor{wordtype}{\\thepage}}
\\fancypagestyle{plain}{\\pagestyle{fancy}}

% ---------- entry command  \\entry{word}{type}{defs}{examples} ----------
\\newcommand{\\entry}[4]{%
  \\item[]%
  {\\sffamily\\large\\bfseries\\color{headword}\\scshape #1}%
  \\hspace{0.5em}%
  {\\sffamily\\small\\itshape\\color{wordtype}#2}\\par\\vspace{2pt}%
  \\begin{enumerate}[label=\\color{headword}\\arabic*.,
                    leftmargin=1.4em, topsep=2pt, itemsep=1pt]
    #3
  \\end{enumerate}
  \\vspace{3pt}%
  {\\sffamily\\small\\bfseries\\color{headword}Beispiele}\\par\\vspace{1pt}%
  \\begin{itemize}[label=\\color{headword}\\textbullet,
                  leftmargin=1.2em, topsep=1pt, itemsep=2pt]
    #4
  \\end{itemize}
  \\vspace{0.6cm}%
}

\\begin{document}
\\begin{itemize}[leftmargin=*]"""

GERMAN_FINAL_TEX_CONTENT = r"""
\\end{itemize}
\\end{document}"""

INITIAL_ENG_DE_TEX_CONTENT = r"""\\documentclass[11pt]{article}

% Dedicated marker: English to German
% ---------- page geometry ----------
\\usepackage[a4paper, margin=0.9in]{geometry}

% ---------- encoding & fonts ----------
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage{ebgaramond}
\\usepackage[scaled=0.88]{sourcesanspro}
\\usepackage{microtype}

% ---------- colour ----------
\\usepackage[dvipsnames,svgnames]{xcolor}
\\definecolor{headword}{HTML}{1B2A4A}
\\definecolor{wordtype}{HTML}{6B6B6B}
% ---------- layout ----------
\\usepackage{enumitem}
\\usepackage{fancyhdr}
\\usepackage[hidelinks]{hyperref}

% ---------- header / footer ----------
\\pagestyle{fancy}
\\fancyhf{}
\\renewcommand{\\headrulewidth}{0pt}
\\fancyfoot[C]{\\sffamily\\small\\textcolor{wordtype}{\\thepage}}
\\fancypagestyle{plain}{\\pagestyle{fancy}}

% ---------- translation pair command ----------
% Usage: \\engde{English Text}{German Translation}
\\newcommand{\\engde}[2]{%
  \\item[]%
  {\\sffamily\\small\\bfseries\\color{headword}EN}\\enspace #1\\\\[2pt]%
  {\\sffamily\\small\\bfseries\\color{headword}DE}\\enspace #2%
  \\vspace{0.6em}%
}

\\begin{document}

\\begin{itemize}[leftmargin=*, itemsep=1ex]
"""

FINAL_ENG_DE_TEX_CONTENT = r"""
\\end{itemize}
\\end{document}
"""

INITIAL_DE_ENG_TEX_CONTENT = r"""\\documentclass[11pt]{article}

% Dedicated marker: German to English
% ---------- page geometry ----------
\\usepackage[a4paper, margin=0.9in]{geometry}

% ---------- encoding & fonts ----------
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage{ebgaramond}
\\usepackage[scaled=0.88]{sourcesanspro}
\\usepackage{microtype}

% ---------- colour ----------
\\usepackage[dvipsnames,svgnames]{xcolor}
\\definecolor{headword}{HTML}{1B2A4A}
\\definecolor{wordtype}{HTML}{6B6B6B}
% ---------- layout ----------
\\usepackage{enumitem}
\\usepackage{fancyhdr}
\\usepackage[hidelinks]{hyperref}

% ---------- header / footer ----------
\\pagestyle{fancy}
\\fancyhf{}
\\renewcommand{\\headrulewidth}{0pt}
\\fancyfoot[C]{\\sffamily\\small\\textcolor{wordtype}{\\thepage}}
\\fancypagestyle{plain}{\\pagestyle{fancy}}

% ---------- translation pair command ----------
% Usage: \\deeng{German Text}{English Translation}
\\newcommand{\\deeng}[2]{%
  \\item[]%
  {\\sffamily\\small\\bfseries\\color{headword}DE}\\enspace #1\\\\[2pt]%
  {\\sffamily\\small\\bfseries\\color{headword}EN}\\enspace #2%
  \\vspace{0.6em}%
}

\\begin{document}

\\begin{itemize}[leftmargin=*, itemsep=1ex]
"""

FINAL_DE_ENG_TEX_CONTENT = r"""
\\end{itemize}
\\end{document}
"""
