"""
VocabRepository: LaTeX vocabulary persistence and entry management.

Extracted from FrenchVocabBuilder to handle:
- Loading/saving vocabulary entries from LaTeX files
- Entry insertion, alphabetization, and updates
- Duplicate detection via normalized lookups
- Thread-safe lazy loading of entries
"""

import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from latex_repository import LatexRepository
from models import normalize_word_key
from languages import LanguageConfig, get_language_config
from ui_helper import UIHelper


class VocabRepository:
    """Manages vocabulary entries stored in LaTeX files."""

    DEFAULT_LANGUAGE_CONFIG = get_language_config(None)

    def __init__(
        self,
        latex_file: Path,
        entry_command: str,
        language_config: LanguageConfig,
        ui: UIHelper,
        vocab_template: Any = None,
    ):
        """
        Initialize the vocabulary repository.

        Args:
            latex_file: Path to the LaTeX vocabulary file
            entry_command: LaTeX command for entries (e.g., '\\entry')
            language_config: Language configuration
            ui: UIHelper instance for user feedback
            vocab_template: Vocabulary template configuration
        """
        self.latex_file = latex_file
        self.entry_command = entry_command
        self.language_config = language_config
        self.ui = ui
        self.vocab_template = vocab_template or language_config.vocab

        # Repository for LaTeX entries (balanced-brace parser)
        self.repo = LatexRepository(latex_file, entry_command=entry_command)

        # Entry storage
        self.word_entries: Dict[str, Dict] = {}
        self.normalized_entries: Dict[str, str] = {}
        self.entry_count: int = 0

        # Thread-safe lazy loading state
        self._entries_lock = threading.Lock()
        self._entries_loaded: bool = False
        self._entries_loading: bool = False
        self._entries_ready = threading.Event()

        # Caching for count_entries
        self._entry_count_snapshot: Optional[Tuple[float, int, int]] = None

    def _get_entry_command(self) -> str:
        """Get the LaTeX entry command with backslash prefix."""
        entry_cmd = self.entry_command
        if not entry_cmd.startswith('\\'):
            entry_cmd = f"\\{entry_cmd}"
        return entry_cmd

    # -------------------------------------------------------------------------
    # File Creation
    # -------------------------------------------------------------------------

    def create_initial_tex_file(self) -> None:
        """Create an initial LaTeX vocabulary file from template."""
        try:
            template = self.vocab_template
            # Create the parent directory if needed
            if self.latex_file.parent != Path('.'):
                self.latex_file.parent.mkdir(parents=True, exist_ok=True)
            with self.latex_file.open('w', encoding='utf-8') as file:
                file.write(template.initial_content)
                sample = template.sample_entry or ""
                if sample:
                    file.write(sample)
                file.write(template.final_content)
            self.ui.success(f"Created initial LaTeX file: {self.latex_file}")
        except IOError as e:
            self.ui.error(f"Error creating initial LaTeX file: {e}", with_panel=True)
            raise

    # -------------------------------------------------------------------------
    # Entry Loading
    # -------------------------------------------------------------------------

    def ensure_entries_loaded(self) -> None:
        """Load LaTeX entries on first access to avoid startup penalty."""
        if self._entries_loaded:
            return

        with self._entries_lock:
            if self._entries_loaded:
                self._entries_ready.set()
                return
            if self._entries_loading:
                self._entries_ready.wait(timeout=1.0)
                return

            # Check if entries already populated
            if self.word_entries:
                self._entries_loaded = True
                self._entries_ready.set()
                return

            self._entries_loading = True

        try:
            self.load_existing_entries()
            self._entries_loaded = True
        except Exception:
            self._entries_loaded = False
            raise
        finally:
            self._entries_loading = False
            self._entries_ready.set()

    def load_existing_entries(self) -> None:
        """Load existing vocabulary entries using a balanced-brace parser."""
        self.word_entries.clear()
        self.normalized_entries.clear()

        entries = self.repo.load_entries()
        key_collisions: Dict[str, List[str]] = {}

        for e in entries:
            word = (e.word or "").strip()
            if not word:
                self.ui.warning(f"Skipping entry due to content: '{e.word or '[EMPTY WORD]'}'")
                continue

            if not e.definitions:
                self.ui.warning(f"Entry '{word}' is missing definitions; keeping it with an empty definition list.")
            if not e.examples:
                self.ui.warning(f"Entry '{word}' is missing examples; keeping it with an empty example list.")

            key = word.lower()
            if key in self.word_entries:
                key_collisions.setdefault(key, [self.word_entries[key]['word']]).append(e.word)

            definitions = list(e.definitions or [])
            examples = list(e.examples or [])
            self.word_entries[key] = {
                'word': word,
                'type': e.type or "",
                'definitions': "; ".join(definitions),
                'examples': "; ".join([f"{fr} ({en})" if en else fr for fr, en in examples]),
                'definitions_list': definitions,
                'examples_list': examples,
            }
            norm = self.normalize_word(key)
            self.normalized_entries[norm] = key

        if key_collisions:
            self.ui.panel(
                f"[bold yellow]WARNING:[/bold yellow] {len(key_collisions)} duplicate word key(s) detected during loading, "
                f"resulting in {sum(len(v) - 1 for v in key_collisions.values())} overwritten entries.\n"
                "The application uses the *last* encountered entry for each duplicate word.\n"
                "Please review your `.tex` file and remove redundant entries for:\n" +
                "\n".join([f" - Key: '{key}' (from words: {', '.join(words)})" for key, words in key_collisions.items()]),
                title="Duplicate Entries Found",
                border_style="yellow"
            )

        self.entry_count = len(self.word_entries)
        self._entries_loaded = True

    def count_entries(self) -> int:
        """Count entries with file stat caching for performance."""
        try:
            stat = self.latex_file.stat()
        except FileNotFoundError:
            self.ui.error(f"File not found - {self.latex_file}", with_panel=True)
            self._entry_count_snapshot = None
            return 0

        signature = (stat.st_mtime, stat.st_size)
        if (
            self._entry_count_snapshot is not None
            and self._entry_count_snapshot[0] == signature[0]
            and self._entry_count_snapshot[1] == signature[1]
        ):
            return self._entry_count_snapshot[2]

        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()
        except Exception as exc:
            self.ui.error(f"Error reading file: {exc}", with_panel=True)
            return 0

        cmd_pattern = re.escape(self._get_entry_command()) + r"\{"
        count = len(re.findall(cmd_pattern, content))
        self._entry_count_snapshot = (signature[0], signature[1], count)
        return count

    # -------------------------------------------------------------------------
    # Normalization & Lookup
    # -------------------------------------------------------------------------

    @staticmethod
    def normalize_word(word: str) -> str:
        """Normalize a word by converting to lowercase and removing accents."""
        return normalize_word_key(word)

    def check_duplicate(self, word: str) -> Optional[str]:
        """Check if a word already exists (returns existing key if duplicate)."""
        self.ensure_entries_loaded()
        normalized_word = self.normalize_word(word)
        return self.normalized_entries.get(normalized_word)

    def get_all_latex_entries(self) -> Set[str]:
        """Return a set of all words in the LaTeX file."""
        with self.latex_file.open("r", encoding="utf-8") as file:
            content = file.read()
        entry_cmd_pattern = re.escape(self._get_entry_command()) + r"\{(.*?)\}"
        entries = re.findall(entry_cmd_pattern, content)
        return set(entry.lower() for entry in entries)

    # -------------------------------------------------------------------------
    # Entry Modification
    # -------------------------------------------------------------------------

    def add_word_to_entries(
        self,
        word: str,
        word_type: str,
        definitions: List[str],
        examples: List[Tuple[str, str]],
    ) -> None:
        """Update the in-memory dictionaries with a new word entry."""
        self._entries_loaded = True
        word_lower = word.lower()
        display_word = word if word_type.lower() == 'sentence' else word.capitalize()
        self.word_entries[word_lower] = {
            "word": display_word,
            "type": word_type,
            "definitions": "; ".join(definitions),
            "examples": "; ".join([f"{f} ({e})" for f, e in examples]),
            "definitions_list": list(definitions),
            "examples_list": list(examples),
        }
        # Update normalized entries as well
        normalized_word = self.normalize_word(word_lower)
        self.normalized_entries[normalized_word] = word_lower
        self.entry_count = len(self.word_entries)

    def insert_entry_alphabetically(self, new_entry: str, new_word: str) -> None:
        """Insert a new LaTeX entry at the appropriate position."""
        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            entry_cmd = self._get_entry_command()
            last_entry_index = content.rfind(entry_cmd)
            if last_entry_index == -1:
                # No existing entries; place before \end{itemize} or \end{document}
                insert_position = content.rfind("\\end{itemize}")
                if insert_position == -1:
                    insert_position = content.rfind("\\end{document}")
                    if insert_position == -1:
                        insert_position = len(content)
            else:
                insert_position = content.find("\\end{itemize}", last_entry_index)
                if insert_position == -1:
                    insert_position = content.rfind("\\end{document}")
                    if insert_position == -1:
                        insert_position = len(content)

            updated_content = content[:insert_position] + new_entry + "\n\n" + content[insert_position:]

            with self.latex_file.open("w", encoding="utf-8") as file:
                file.write(updated_content)

            # Update the normalized entries dictionary after successful file write
            normalized_new_word = self.normalize_word(new_word)
            self.normalized_entries[normalized_new_word] = new_word.capitalize()

            self.ui.success(f"Added/Updated entry for '{new_word}' in {self.latex_file}")
        except FileNotFoundError:
            self.ui.error(
                f"Cannot insert entry: File not found\n{self.latex_file}",
                with_panel=True
            )
        except IOError as e:
            self.ui.error(
                f"Cannot insert entry: File I/O error\n{e}",
                with_panel=True
            )

    def alphabetize_entries(self, *, silent: bool = False) -> None:
        """Alphabetize the entries in the LaTeX file."""
        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            # Find the main vocab list itemize
            itemize_header_match = re.search(
                r"\\begin{itemize}\[[^\]]*leftmargin[^\]]*\]",
                content,
                re.IGNORECASE
            )
            if not itemize_header_match:
                self.ui.error("Could not find the entries section.")
                return
            entries_start = itemize_header_match.start()
            header_line = itemize_header_match.group(0)
            entries_end = content.find("\\end{itemize}", itemize_header_match.end())

            if entries_end == -1:
                self.ui.error("Could not find the end of the entries section.")
                return

            header = content[:entries_start]
            entries_section = content[itemize_header_match.end():entries_end]
            footer = content[entries_end:]

            # Regex pattern for entries
            entry_cmd_pattern = re.escape(self._get_entry_command())
            entry_pattern = rf"""
                {entry_cmd_pattern}
                \s*\{{
                    (?P<word>[^{{}}]+)
                \}}
                \s*\{{
                    (?P<type>[^{{}}]+)
                \}}
                \s*\{{
                    (?P<defs> (?: [^{{}}]+ | \{{[^{{}}]*\}} )* )
                \}}
                \s*\{{
                    (?P<exs>  (?: [^{{}}]+ | \{{[^{{}}]*\}} )* )
                \}}
            """

            entry_matches = list(re.finditer(entry_pattern, entries_section, re.VERBOSE | re.DOTALL))

            if not entry_matches:
                if not silent:
                    self.ui.warning("No entries found to alphabetize.")
                return

            # Extract full entry text and word for sorting
            entries = []
            for match in entry_matches:
                start, end = match.span()
                full_entry = entries_section[start:end]
                word = match.group('word')
                entries.append((word, full_entry))

            # Sort entries by normalized word
            sorted_entries = sorted(entries, key=lambda x: self.normalize_word(x[0]))

            # Reconstruct the entries section
            sorted_entries_section = header_line + "\n" + "\n\n".join([entry for _, entry in sorted_entries])
            sorted_content = header + sorted_entries_section + footer

            # Safety check
            if len(sorted_content) < len(content) * 0.9:
                self.ui.error("Warning: Significant content loss detected. Aborting alphabetization.")
                return

            with self.latex_file.open("w", encoding="utf-8") as file:
                file.write(sorted_content)

            if not silent:
                self.ui.success("Entries alphabetized successfully.")
        except FileNotFoundError:
            self.ui.error(
                f"Cannot alphabetize: File not found\n{self.latex_file}",
                with_panel=True
            )
        except IOError as e:
            self.ui.error(
                f"Cannot alphabetize: File I/O error\n{e}",
                with_panel=True
            )

    def update_entry_in_file(self, word_capitalized: str, new_block: str) -> None:
        """Replace the LaTeX entry block for the given word with new_block."""
        try:
            with self.latex_file.open("r", encoding="utf-8") as f:
                content = f.read()

            entry_cmd_pattern = re.escape(self._get_entry_command())
            word_pattern = re.escape(word_capitalized)
            pattern = rf"""
                {entry_cmd_pattern}
                \{{{word_pattern}\}}
                \{{[^{{}}]*\}}
                \{{ (?: [^{{}}]+ | \{{[^{{}}]*\}} )* \}}
                \{{ (?: [^{{}}]+ | \{{[^{{}}]*\}} )* \}}
            """
            new_content, n = re.subn(pattern, new_block, content, count=1, flags=re.VERBOSE | re.DOTALL)
            if n == 0:
                self.ui.warning(f"Could not locate LaTeX entry for '{word_capitalized}' to update. Skipping file update.")
                return
            with self.latex_file.open("w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            self.ui.error(f"Failed to update LaTeX entry for '{word_capitalized}': {e}")

    def is_valid_latex_entry(self, latex_entry: str) -> bool:
        """Check if the entry contains expected LaTeX structure."""
        entry_cmd = self._get_entry_command()
        return bool(latex_entry.strip()) and entry_cmd in latex_entry

    # -------------------------------------------------------------------------
    # Static Formatting
    # -------------------------------------------------------------------------

    @staticmethod
    def format_latex_entry(
        word: str,
        word_type: str,
        definitions: List[str],
        examples: List[Tuple[str, str]],
        entry_command: Optional[str] = None,
    ) -> str:
        """
        Format word information into a LaTeX entry.

        Args:
            word: The vocabulary word
            word_type: The type of word (noun, verb, etc.)
            definitions: List of definitions
            examples: List of (source, translation) example tuples
            entry_command: LaTeX command to use (defaults to config)

        Returns:
            Formatted LaTeX entry string
        """
        # LaTeX escape helper
        def escape_latex(text: str) -> str:
            if text is None:
                return ""
            mapping = {
                '&': r'\&',
                '%': r'\%',
                '$': r'\$',
                '#': r'\#',
                '_': r'\_',
                '{': r'\{',
                '}': r'\}',
                '~': r'\textasciitilde{}',
                '^': r'\textasciicircum{}',
                '\\': r'\textbackslash{}',
            }
            pattern = re.compile('|'.join(re.escape(k) for k in sorted(mapping.keys(), key=len, reverse=True)))
            return pattern.sub(lambda m: mapping[m.group(0)], text)

        # Determine which LaTeX command to use
        entry_cmd = entry_command or VocabRepository.DEFAULT_LANGUAGE_CONFIG.vocab.entry_command
        if not entry_cmd.startswith('\\'):
            entry_cmd = f"\\{entry_cmd}"

        # Capitalize and escape word and type
        capitalized_word = escape_latex(word if word_type.lower() == 'sentence' else word.capitalize())
        escaped_type = escape_latex(word_type)

        # Escape definitions and examples
        def_items = "".join([f"    \\item {escape_latex(d)}\n" for d in definitions])

        example_lines = []
        for fr, en in examples:
            fr_esc = escape_latex(fr)
            en_esc = escape_latex(en)
            english_part = en_esc if (en_esc.startswith('(') and en_esc.endswith(')')) else f'({en_esc})'
            example_lines.append(f"    \\item {fr_esc} \\\\ {english_part}\n")
        example_items = "".join(example_lines)

        latex_entry = f"""{entry_cmd}{{{capitalized_word}}}{{{escaped_type}}}
      {{
    {def_items.rstrip()}
      }}
      {{
    {example_items.rstrip()}
      }}"""

        return latex_entry
