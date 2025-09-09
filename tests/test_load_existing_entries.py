import os
import unittest
from pathlib import Path
import tempfile

import sys
sys.path.append(str(Path(__file__).parent))
from _stubs import install_basic_stubs
install_basic_stubs()

import FrenchVocab


SIMPLE_TEX = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\newcommand{\entry}[4]{\item \textbf{#1} (#2)\begin{enumerate}#3\end{enumerate}\begin{itemize}#4\end{itemize}}
\begin{document}
\begin{itemize}[leftmargin=*]
\entry{Abîmer}{'noun'}
      {
        \item To damage
      }
      {
        \item Il ne faut pas abîmer les meubles. \\ (We must not damage the furniture.)
      }
\entry{Cafe}{expression}
      {
        \item A small restaurant
      }
      {
        \item On va au cafe. \\ (We are going to the cafe.)
      }
\end{itemize}
\end{document}
"""


class TestLoadExistingEntries(unittest.TestCase):
    def setUp(self):
        os.environ['GEMINI_API_KEY'] = 'x'*40  # pass basic length check

    def test_load_parses_basic_entries_and_normalizes_type(self):
        with tempfile.TemporaryDirectory() as td:
            tex_path = Path(td) / 'FrenchVocab.tex'
            tex_path.write_text(SIMPLE_TEX, encoding='utf-8')

            app = FrenchVocab.FrenchVocabBuilder(str(tex_path), provider='gemini', verbose=False)
            # Should parse 2 entries
            self.assertIn('abîmer', app.word_entries)
            self.assertIn('cafe', app.word_entries)

            ab = app.word_entries['abîmer']
            self.assertEqual(ab['type'], "noun")  # stripped quotes
            self.assertIn('definitions_list', ab)
            self.assertEqual(ab['definitions_list'][0].lower().startswith('to damage'), True)
            self.assertTrue(ab['examples_list'][0][0].startswith('Il ne faut pas'))
            self.assertIn('We must not damage', ab['examples_list'][0][1])

            # normalized entries map accent-free key to canonical key
            norm_key = app.normalize_word('Abîmer')
            self.assertEqual(app.normalized_entries[norm_key], 'abîmer')


if __name__ == '__main__':
    unittest.main()
