import unittest
import tempfile
import os
from FrenchVocab import FrenchVocabBuilder

class TestFrenchVocabBuilder(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "test_vocab.tex")
        print(f"Created temporary file: {self.test_file}")

        # Create an empty file
        with open(self.test_file, 'w', encoding='utf-8') as f:
            pass  # This creates an empty file

        self.builder = FrenchVocabBuilder(self.test_file)

    def tearDown(self):
        os.remove(self.test_file)
        os.rmdir(self.temp_dir)

    def write_test_file(self, content):
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write(content)

    def read_test_file(self):
        with open(self.test_file, "r", encoding="utf-8") as f:
            return f.read()

    def test_basic_alphabetization(self):
        content = r"""
\documentclass{article}
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

\begin{document}

\begin{itemize}[leftmargin=*]
\entry{Zèbre}{noun}
  {
    \item A striped African equine
  }
  {
    \item Le zèbre court dans la savane. \\ (The zebra runs in the savannah.)
  }

\entry{Abeille}{noun}
  {
    \item A honey bee
  }
  {
    \item L'abeille butine une fleur. \\ (The bee is foraging on a flower.)
  }
\end{itemize}

\end{document}
"""
        self.write_test_file(content)
        self.builder.alphabetize_entries()
        result = self.read_test_file()
        self.assertIn(r"\entry{Abeille}", result.split(r"\entry{Zèbre}")[0])

    def test_preserve_structure(self):
        content = r"""
\documentclass{article}
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

\begin{document}

\begin{itemize}[leftmargin=*]
\entry{Chat}{noun}
  {
    \item A cat
  }
  {
    \item Le chat dort sur le canapé. \\ (The cat is sleeping on the couch.)
  }
\end{itemize}

\section{Additional Notes}
Some extra content here.

\end{document}
"""
        self.write_test_file(content)
        self.builder.alphabetize_entries()
        result = self.read_test_file()
        self.assertIn(r"\documentclass{article}", result)
        self.assertIn(r"\section{Additional Notes}", result)
        self.assertIn(r"\end{document}", result)

    def test_multiple_entries(self):
        content = r"""
        \begin{itemize}[leftmargin=*]
        \entry{Chien}{noun}
          {
            \item A dog
          }
          {
            \item Le chien aboie. \\ (The dog barks.)
          }

        \entry{Baleine}{noun}
          {
            \item A whale
          }
          {
            \item La baleine nage dans l'océan. \\ (The whale swims in the ocean.)
          }

        \entry{Aigle}{noun}
          {
            \item An eagle
          }
          {
            \item L'aigle vole haut dans le ciel. \\ (The eagle flies high in the sky.)
          }
        \end{itemize}
        """
        print("Original content:")
        print(content)

        self.write_test_file(content)
        self.builder.alphabetize_entries()
        result = self.read_test_file()

        print("\nAlphabetized content:")
        print(result)

        entries = result.split(r"\entry{")
        print("\nEntries after splitting:")
        for i, entry in enumerate(entries):
            print(f"{i}: {entry[:50]}...")  # Print first 50 chars of each entry

        # Modified assertions
        self.assertTrue(any(entry.startswith("Aigle") for entry in entries),
                        "Aigle entry is missing from the alphabetized list")
        self.assertTrue(any(entry.startswith("Baleine") for entry in entries),
                        "Baleine entry is missing from the alphabetized list")
        self.assertTrue(any(entry.startswith("Chien") for entry in entries),
                        "Chien entry is missing from the alphabetized list")

        aigle_index = next(i for i, entry in enumerate(entries) if entry.startswith("Aigle"))
        baleine_index = next(i for i, entry in enumerate(entries) if entry.startswith("Baleine"))
        chien_index = next(i for i, entry in enumerate(entries) if entry.startswith("Chien"))

        self.assertGreater(aigle_index, 0, "Aigle should not be the first entry")
        self.assertGreater(baleine_index, aigle_index, "Baleine should come after Aigle")
        self.assertGreater(chien_index, baleine_index, "Chien should come after Baleine")
    def test_accented_characters(self):
        content = r"""
\begin{itemize}[leftmargin=*]
\entry{Élève}{noun}
  {
    \item A student
  }
  {
    \item L'élève étudie pour son examen. \\ (The student is studying for their exam.)
  }

\entry{École}{noun}
  {
    \item A school
  }
  {
    \item L'école est fermée aujourd'hui. \\ (The school is closed today.)
  }
\end{itemize}
"""
        self.write_test_file(content)
        self.builder.alphabetize_entries()
        result = self.read_test_file()
        self.assertIn(r"\entry{École}", result.split(r"\entry{Élève}")[0])

    def test_empty_file(self):
        content = r"""
\documentclass{article}
\begin{document}
\end{document}
"""
        self.write_test_file(content)
        self.builder.alphabetize_entries()
        result = self.read_test_file()
        self.assertEqual(content.strip(), result.strip())

    def test_single_entry(self):
        content = r"""
\begin{itemize}[leftmargin=*]
\entry{Unique}{adjective}
  {
    \item Being the only one of its kind
  }
  {
    \item Cette pièce est unique. \\ (This piece is unique.)
  }
\end{itemize}
"""
        self.write_test_file(content)
        self.builder.alphabetize_entries()
        result = self.read_test_file()
        self.assertIn(r"\entry{Unique}", result)
        self.assertEqual(content.strip(), result.strip())

if __name__ == '__main__':
    unittest.main()

