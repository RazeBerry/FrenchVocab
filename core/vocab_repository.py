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

from core.file_safety import atomic_write_text
from latex_repository import LatexRepository, find_entry_bounds, parse_all_entries
from models import normalize_word_key
from languages import LanguageConfig, get_language_config
from ui_helper import UIHelper


class EntryNotFoundError(Exception):
    """Raised when a vocabulary entry cannot be located in the LaTeX file."""
    pass


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
        # Thread-safe fast path using Event (avoids lock for common case)
        if self._entries_ready.is_set():
            return

        should_load = False
        with self._entries_lock:
            # Re-check under lock
            if self._entries_ready.is_set():
                return

            if self._entries_loading:
                # Another thread is loading - we'll wait outside the lock
                pass
            elif self.word_entries:
                # Entries already populated (shouldn't happen, but be safe)
                self._entries_loaded = True
                self._entries_ready.set()
                return
            else:
                # We're the loading thread
                self._entries_loading = True
                should_load = True

        if should_load:
            try:
                self.load_existing_entries()
                self._entries_loaded = True
            except Exception:
                self._entries_loaded = False
                raise
            finally:
                self._entries_loading = False
                self._entries_ready.set()
        else:
            # Wait for loading thread to finish (30s timeout for large files)
            if not self._entries_ready.wait(timeout=30.0):
                raise TimeoutError("Timed out waiting for vocabulary entries to load")

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
        """Insert a new LaTeX entry at the correct alphabetical position.

        Uses balanced-brace parsing to find existing entries and determine
        the correct insertion point.
        """
        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            entry_cmd = self._get_entry_command()
            new_word_normalized = self.normalize_word(new_word)

            # Parse all existing entries
            parsed_entries = parse_all_entries(content, entry_cmd)

            if not parsed_entries:
                # No existing entries; place before \end{itemize} or \end{document}
                insert_position = content.rfind("\\end{itemize}")
                if insert_position == -1:
                    insert_position = content.rfind("\\end{document}")
                    if insert_position == -1:
                        insert_position = len(content)
            else:
                # Find the correct alphabetical position
                insert_position = None
                for groups, start, end in parsed_entries:
                    entry_word = groups[0].strip()
                    entry_word_normalized = self.normalize_word(entry_word)
                    if new_word_normalized < entry_word_normalized:
                        # Insert before this entry
                        insert_position = start
                        break

                if insert_position is None:
                    # New word comes after all existing entries
                    # Insert after the last entry, before \end{itemize}
                    _, _, last_end = parsed_entries[-1]
                    insert_position = content.find("\\end{itemize}", last_end)
                    if insert_position == -1:
                        insert_position = content.rfind("\\end{document}")
                        if insert_position == -1:
                            insert_position = len(content)

            updated_content = content[:insert_position] + new_entry + "\n\n" + content[insert_position:]

            atomic_write_text(self.latex_file, updated_content, create_backup=True)

            # Update the normalized entries dictionary after successful file write
            normalized_new_word = self.normalize_word(new_word)
            self.normalized_entries[normalized_new_word] = new_word.lower()

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
        """Alphabetize the entries in the LaTeX file.

        Uses balanced-brace parsing to correctly handle nested LaTeX macros.
        """
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

            # Use balanced-brace parser instead of regex
            entry_cmd = self._get_entry_command()
            parsed_entries = parse_all_entries(entries_section, entry_cmd)

            if not parsed_entries:
                if not silent:
                    self.ui.warning("No entries found to alphabetize.")
                return

            # Extract full entry text and word for sorting
            entries = []
            for groups, start, end in parsed_entries:
                full_entry = entries_section[start:end]
                word = groups[0].strip()  # First group is the word
                entries.append((word, full_entry))

            original_entry_count = len(parsed_entries)

            # Sort entries by normalized word
            sorted_entries = sorted(entries, key=lambda x: self.normalize_word(x[0]))

            # Reconstruct the entries section
            sorted_entries_section = header_line + "\n" + "\n\n".join([entry for _, entry in sorted_entries])
            sorted_content = header + sorted_entries_section + footer

            # Safety check: verify entry count matches
            sorted_entry_count = len(sorted_entries)

            if sorted_entry_count != original_entry_count:
                loss_count = original_entry_count - sorted_entry_count
                self.ui.error(
                    f"Entry count mismatch detected: {original_entry_count} entries before, "
                    f"{sorted_entry_count} after ({loss_count} would be lost). "
                    "Aborting alphabetization to prevent data loss."
                )
                return

            atomic_write_text(self.latex_file, sorted_content, create_backup=True)

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
        """Replace the LaTeX entry block for the given word with new_block.

        Uses balanced-brace parsing to correctly handle nested LaTeX macros.

        Raises:
            EntryNotFoundError: If the entry cannot be located in the file.
            IOError: If file read/write operations fail.
        """
        with self.latex_file.open("r", encoding="utf-8") as f:
            content = f.read()

        entry_cmd = self._get_entry_command()
        bounds = find_entry_bounds(content, entry_cmd, word_capitalized)

        if bounds is None:
            raise EntryNotFoundError(
                f"Could not locate LaTeX entry for '{word_capitalized}' in file. "
                f"The entry may have been manually modified or deleted."
            )

        start, end = bounds
        new_content = content[:start] + new_block + content[end:]
        atomic_write_text(self.latex_file, new_content, create_backup=True)

    def is_valid_latex_entry(self, latex_entry: str) -> bool:
        """Check if the entry contains expected LaTeX structure."""
        entry_cmd = self._get_entry_command()
        return bool(latex_entry.strip()) and entry_cmd in latex_entry

    def merge_into_existing(
        self,
        existing_word: str,
        new_type: str,
        new_defs: List[str],
        new_examples: List[Tuple[str, str]],
    ) -> bool:
        """Merge new definitions/examples into an existing entry and update the LaTeX file.

        Args:
            existing_word: The word key to merge into
            new_type: Word type from the new entry
            new_defs: New definitions to merge
            new_examples: New examples to merge

        Returns:
            True if merge was successful, False otherwise.

        Note:
            Uses transactional approach: file is updated first, then memory.
            If file update fails, memory remains unchanged (no partial state).
        """
        self.ensure_entries_loaded()
        key = existing_word.lower()
        if key not in self.word_entries:
            self.ui.error(f"Cannot merge: existing entry for '{existing_word}' not found.")
            return False
        entry = self.word_entries[key]

        # Use structured lists if available else fallback with robust parsing
        defs_existing = entry.get('definitions_list') or [
            d.strip() for d in entry['definitions'].split('; ') if d.strip()
        ]
        exs_existing = entry.get('examples_list') or []
        if not exs_existing and entry.get('examples'):
            exs_existing = self._parse_examples_string(entry['examples'])

        # Dedup helpers with accent normalization
        def norm_text(s: str) -> str:
            """Normalize text for deduplication: lowercase, strip accents, collapse whitespace."""
            import re
            text = re.sub(r"\s+", " ", s).strip().lower()
            return normalize_word_key(text)

        def norm_pair(p: Tuple[str, str]) -> Tuple[str, str]:
            return (norm_text(p[0]), norm_text(p[1]))

        merged_defs_map = {norm_text(d): d for d in defs_existing}
        added_defs: List[str] = []
        for d in new_defs:
            nd = norm_text(d)
            if nd and nd not in merged_defs_map:
                merged_defs_map[nd] = d
                added_defs.append(d)
        merged_defs = list(merged_defs_map.values())

        merged_exs_map = {norm_pair(p): p for p in exs_existing}
        added_examples: List[Tuple[str, str]] = []
        for p in new_examples:
            np = norm_pair(p)
            if np not in merged_exs_map:
                merged_exs_map[np] = p
                added_examples.append(p)
        merged_exs = list(merged_exs_map.values())

        # Keep existing type by default; if unknown, use new
        final_type = entry.get('type') or new_type

        # Rebuild LaTeX entry and replace in file
        latex_block = self.format_latex_entry(
            entry['word'],
            final_type,
            merged_defs,
            merged_exs,
            entry_command=self.entry_command,
        )

        # Transactional: Update file FIRST, then memory
        try:
            self.update_entry_in_file(entry['word'], latex_block)
        except EntryNotFoundError as e:
            self.ui.error(f"Merge failed: {e}", with_panel=True)
            return False
        except IOError as e:
            self.ui.error(f"Merge failed - file I/O error: {e}", with_panel=True)
            return False

        # File updated successfully, now update memory
        entry['type'] = final_type
        entry['definitions_list'] = merged_defs
        entry['examples_list'] = merged_exs
        entry['definitions'] = "; ".join(merged_defs)
        entry['examples'] = "; ".join([f"{f} ({e})" for f, e in merged_exs])

        return True

    def _parse_examples_string(self, examples_str: str) -> List[Tuple[str, str]]:
        """Robustly parse examples string into (source, translation) tuples."""
        result: List[Tuple[str, str]] = []
        if not examples_str:
            return result

        for example in examples_str.split('; '):
            example = example.strip()
            if not example:
                continue

            # Find the last balanced parentheses group
            parsed = self._extract_translation_from_parens(example)
            if parsed:
                result.append(parsed)
            else:
                # If no valid parens found, treat whole thing as source
                self.ui.warning(f"Could not parse example translation: '{example[:50]}...'")
                result.append((example, ""))

        return result

    def _extract_translation_from_parens(self, text: str) -> Optional[Tuple[str, str]]:
        """Extract (source, translation) from 'source text (translation)' format."""
        text = text.rstrip()
        if not text.endswith(')'):
            return None

        # Find the matching opening paren for the final closing paren
        depth = 0
        for i in range(len(text) - 1, -1, -1):
            if text[i] == ')':
                depth += 1
            elif text[i] == '(':
                depth -= 1
                if depth == 0:
                    source = text[:i].rstrip()
                    translation = text[i + 1:-1]
                    if source:
                        return (source, translation)
                    return None
        return None

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
