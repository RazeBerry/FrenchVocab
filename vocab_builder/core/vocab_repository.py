"""
VocabRepository: LaTeX vocabulary persistence and entry management.

Extracted from VocabBuilder to handle:
- Loading/saving vocabulary entries from LaTeX files
- Entry insertion, alphabetization, and updates
- Duplicate detection via normalized lookups
- Thread-safe lazy loading of entries
"""

import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from vocab_builder.core.bulk_add import BulkAddReport, DuplicatePolicy
from vocab_builder.core.file_safety import atomic_copy_file, atomic_write_text, file_lock
from vocab_builder.latex_repository import LatexRepository, find_entry_bounds, iter_entry_groups, parse_all_entries
from vocab_builder.models import WordEntry, normalize_word_key
from vocab_builder.languages import LanguageConfig, get_language_config
from vocab_builder.ui_helper import UIHelper

_LATEX_ESCAPE_MAPPING = {
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
_LATEX_ESCAPE_PATTERN = re.compile(
    "|".join(
        re.escape(k)
        for k in sorted(_LATEX_ESCAPE_MAPPING.keys(), key=len, reverse=True)
    )
)


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
        self.duplicate_entry_keys: Dict[str, List[str]] = {}
        self.entry_count: int = 0

        # Thread-safe lazy loading state
        self._entries_lock = threading.Lock()
        self._entries_loaded: bool = False
        self._entries_loading: bool = False
        self._entries_ready = threading.Event()
        self._loaded_file_signature: Optional[Tuple[int, int, int, int]] = None

        self._reported_load_issues: Set[str] = set()

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
        with file_lock(self.latex_file):
            if self.latex_file.exists():
                self.ui.warning(f"Initial LaTeX file already exists; leaving it unchanged: {self.latex_file}")
                return
            backup_path = self._backup_path()
            if backup_path.exists() and backup_path.is_file():
                self._restore_from_backup_if_available()
                return
            try:
                template = self.vocab_template
                # Create the parent directory if needed
                if self.latex_file.parent != Path('.'):
                    self.latex_file.parent.mkdir(parents=True, exist_ok=True)
                with self.latex_file.open('x', encoding='utf-8') as file:
                    file.write(template.initial_content)
                    sample = template.sample_entry or ""
                    if sample:
                        file.write(sample)
                    file.write(template.final_content)
                self.ui.success(f"Created initial LaTeX file: {self.latex_file}")
            except FileExistsError:
                self.ui.warning(f"Initial LaTeX file already exists; leaving it unchanged: {self.latex_file}")
            except IOError as e:
                self.ui.error(f"Error creating initial LaTeX file: {e}", with_panel=True)
                raise

    def _backup_path(self) -> Path:
        return self.latex_file.with_suffix(self.latex_file.suffix + ".bak")

    def _restore_from_backup_if_available(self) -> bool:
        backup_path = self._backup_path()
        if not backup_path.exists() or not backup_path.is_file():
            return False
        try:
            if self.latex_file.parent != Path('.'):
                self.latex_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_copy_file(backup_path, self.latex_file)
            self.ui.warning(
                f"{self.latex_file} was missing; restored it from backup {backup_path}."
            )
            return True
        except OSError as exc:
            self.ui.error(
                f"Failed to restore {self.latex_file} from backup {backup_path}: {exc}",
                with_panel=True,
            )
            return False

    # -------------------------------------------------------------------------
    # Entry Loading
    # -------------------------------------------------------------------------

    def ensure_entries_loaded(self) -> None:
        """Load entries lazily and refresh after another process changes the file."""
        while True:
            current_signature = self._current_file_signature()
            with self._entries_lock:
                if (
                    self._entries_loaded
                    and self._loaded_file_signature == current_signature
                ):
                    return

                if self._entries_loaded:
                    # A phone request and a Tailscale SSH CLI session may use
                    # separate processes. Atomic writes protect the file; this
                    # signature check keeps both in-memory indexes current.
                    self._entries_loaded = False

                if self._entries_loading:
                    wait_event = self._entries_ready
                    should_load = False
                else:
                    self._entries_loading = True
                    self._entries_ready.clear()
                    should_load = True
                    wait_event = None

            if should_load:
                load_start_signature = current_signature
                try:
                    self.load_existing_entries()
                except Exception:
                    with self._entries_lock:
                        self._entries_loaded = False
                    raise
                finally:
                    with self._entries_lock:
                        self._entries_loading = False
                        self._entries_ready.set()
                if load_start_signature != self._current_file_signature():
                    # A writer replaced the file while it was being parsed.
                    # Retry rather than attaching the new signature to an old index.
                    with self._entries_lock:
                        self._entries_loaded = False
                    continue
                return

            # Wait for the active loading thread to finish and retry.
            assert wait_event is not None
            if not wait_event.wait(timeout=30.0):
                raise TimeoutError("Timed out waiting for vocabulary entries to load")

    def _current_file_signature(self) -> Optional[Tuple[int, int, int, int]]:
        try:
            stat = self.latex_file.stat()
        except OSError:
            return None
        return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size

    def load_existing_entries(self) -> None:
        """Load existing vocabulary entries using a balanced-brace parser."""
        self.word_entries.clear()
        self.normalized_entries.clear()
        self.duplicate_entry_keys.clear()

        entries = self.repo.load_entries()
        self._report_load_issues(self.repo.last_load_issues)
        key_collisions: Dict[str, List[str]] = {}
        normalized_collisions: Dict[str, List[str]] = {}

        for e in entries:
            word = (e.word or "").strip()
            if not word:
                self.ui.warning(f"Skipping entry due to content: '{e.word or '[EMPTY WORD]'}'")
                continue

            if not e.definitions:
                self.ui.warning(f"Entry '{word}' is missing definitions; keeping it with an empty definition list.")
            if not e.examples:
                self.ui.warning(f"Entry '{word}' is missing examples; keeping it with an empty example list.")

            base_key = word.lower()
            key = self._unique_entry_key(base_key)
            if key != base_key:
                key_collisions.setdefault(base_key, [self.word_entries[base_key]['word']]).append(e.word)
                self.duplicate_entry_keys.setdefault(base_key, []).append(key)

            definitions = list(e.definitions or [])
            examples = list(e.examples or [])
            self.word_entries[key] = {
                'word': word,
                'type': e.type or "",
                'definitions': "; ".join(definitions),
                'examples': "; ".join([f"{fr} ({en})" if en else fr for fr, en in examples]),
                'definitions_list': definitions,
                'examples_list': examples,
                'duplicate_of': base_key if key != base_key else None,
            }
            norm = self.normalize_word(base_key)
            existing_normalized_key = self.normalized_entries.get(norm)
            if existing_normalized_key is None:
                self.normalized_entries[norm] = base_key
            elif existing_normalized_key != base_key:
                normalized_collisions.setdefault(
                    norm,
                    [self.word_entries[existing_normalized_key]['word']],
                ).append(word)

        if key_collisions:
            self.ui.panel(
                f"[bold yellow]WARNING:[/bold yellow] {len(key_collisions)} duplicate word key(s) detected during loading, "
                f"preserving {sum(len(v) - 1 for v in key_collisions.values())} duplicate entries separately.\n"
                "Duplicate entries are visible in browse/export views; duplicate checks use the first encountered entry.\n"
                "Please review your `.tex` file and remove redundant entries for:\n" +
                "\n".join([f" - Key: '{key}' (from words: {', '.join(words)})" for key, words in key_collisions.items()]),
                title="Duplicate Entries Found",
                border_style="yellow"
            )
        if normalized_collisions:
            self.ui.panel(
                f"[bold yellow]WARNING:[/bold yellow] {len(normalized_collisions)} normalized duplicate key(s) detected.\n"
                "All entries remain loaded, but duplicate checks use the first encountered normalized form.\n"
                "Please review entries for:\n" +
                "\n".join(
                    f" - Normalized key: '{key}' (from words: {', '.join(words)})"
                    for key, words in normalized_collisions.items()
                ),
                title="Normalized Duplicate Entries Found",
                border_style="yellow",
            )

        self.entry_count = len(self.word_entries)
        with self._entries_lock:
            self._entries_loaded = True
            self._loaded_file_signature = self._current_file_signature()
            self._entries_ready.set()

    def _unique_entry_key(self, base_key: str) -> str:
        if base_key not in self.word_entries:
            return base_key
        suffix = 2
        while True:
            candidate = f"{base_key}__duplicate_{suffix}"
            if candidate not in self.word_entries:
                return candidate
            suffix += 1

    def count_entries(self) -> int:
        """Return the authoritative parsed entry count."""
        if not self.latex_file.exists():
            self.ui.error(f"File not found - {self.latex_file}", with_panel=True)
            return 0
        self.ensure_entries_loaded()
        return len(self.word_entries)

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
        """Return a set of all words in the LaTeX file using balanced-brace parsing."""
        content = self._read_text_for_scan()
        if content is None:
            return set()
        entry_cmd = self._get_entry_command()
        entries: Set[str] = set()
        for groups, _, _ in iter_entry_groups(content, entry_cmd, num_groups=1):
            word = groups[0].strip()
            if word:
                entries.add(word.lower())
        return entries

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
        current_signature = self._current_file_signature()
        if self._loaded_file_signature != current_signature:
            # The file changed during the save transaction. Reloading is both
            # simpler and safer than trying to merge an index that may have
            # missed an entry written by another process.
            self.load_existing_entries()
            return

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
        self._loaded_file_signature = self._current_file_signature()

    def bulk_add_entries(
        self,
        entries: Sequence[WordEntry],
        *,
        on_duplicate: DuplicatePolicy = "skip",
        dry_run: bool = False,
    ) -> BulkAddReport:
        """Add or merge a batch with one all-or-nothing file write."""
        from vocab_builder.core.bulk_repository import bulk_add_entries_for_repo

        return bulk_add_entries_for_repo(
            self,
            entries,
            on_duplicate=on_duplicate,
            dry_run=dry_run,
        )

    def insert_entry_alphabetically(self, new_entry: str, new_word: str) -> bool:
        """Insert a new LaTeX entry at the correct alphabetical position.

        Uses balanced-brace parsing to find existing entries and determine
        the correct insertion point.

        Returns True if the entry was successfully written to the file.
        """
        try:
            with file_lock(self.latex_file):
                with self.latex_file.open("r", encoding="utf-8") as file:
                    content = file.read()

                entry_cmd = self._get_entry_command()
                if self._contains_word(content, entry_cmd, new_word):
                    self.ui.warning(
                        f"Cannot insert '{new_word}': an equivalent entry already exists."
                    )
                    return False
                insert_position = self._choose_insert_position(content, entry_cmd, new_word)

                updated_content = content[:insert_position] + new_entry + "\n\n" + content[insert_position:]

                atomic_write_text(self.latex_file, updated_content, create_backup=True)

            # Update the normalized entries dictionary after successful file write
            self._register_normalized_word(new_word)

            self.ui.success(f"Added/Updated entry for '{new_word}' in {self.latex_file}")
            return True
        except FileNotFoundError:
            self.ui.error(
                f"Cannot insert entry: File not found\n{self.latex_file}",
                with_panel=True
            )
            return False
        except IOError as e:
            self.ui.error(
                f"Cannot insert entry: File I/O error\n{e}",
                with_panel=True
            )
            return False

    def _choose_insert_position(self, content: str, entry_cmd: str, new_word: str) -> int:
        new_word_normalized = self.normalize_word(new_word)
        insert_position, last_end, saw_entries = self._scan_entries_for_insertion(
            content,
            entry_cmd,
            new_word_normalized,
        )
        if not saw_entries:
            return self._fallback_insert_position_no_entries(content)
        if insert_position is not None:
            return insert_position
        return self._fallback_insert_position_after_last_entry(content, last_end)

    def _contains_word(self, content: str, entry_cmd: str, word: str) -> bool:
        normalized = self.normalize_word(word)
        return any(
            self.normalize_word(groups[0].strip()) == normalized
            for groups, _, _ in iter_entry_groups(content, entry_cmd, num_groups=1)
        )

    def _scan_entries_for_insertion(
        self,
        content: str,
        entry_cmd: str,
        new_word_normalized: str,
    ) -> Tuple[Optional[int], Optional[int], bool]:
        insert_position: Optional[int] = None
        last_end: Optional[int] = None
        saw_entries = False

        for groups, start, end in iter_entry_groups(content, entry_cmd, num_groups=4):
            saw_entries = True
            last_end = end
            entry_word = groups[0].strip()
            if new_word_normalized < self.normalize_word(entry_word):
                insert_position = start
                break

        return insert_position, last_end, saw_entries

    @staticmethod
    def _fallback_insert_position_no_entries(content: str) -> int:
        insert_position = content.rfind("\\end{itemize}")
        if insert_position != -1:
            return insert_position
        insert_position = content.rfind("\\end{document}")
        if insert_position != -1:
            return insert_position
        return len(content)

    @staticmethod
    def _fallback_insert_position_after_last_entry(content: str, last_end: Optional[int]) -> int:
        insert_position = content.find("\\end{itemize}", last_end or 0)
        if insert_position != -1:
            return insert_position
        insert_position = content.rfind("\\end{document}")
        if insert_position != -1:
            return insert_position
        return len(content)

    def _register_normalized_word(self, word: str) -> None:
        normalized = self.normalize_word(word)
        self.normalized_entries[normalized] = word.lower()

    def alphabetize_entries(self, *, silent: bool = False) -> None:
        """Alphabetize the entries in the LaTeX file.

        Uses balanced-brace parsing to correctly handle nested LaTeX macros.
        """
        try:
            with file_lock(self.latex_file):
                with self.latex_file.open("r", encoding="utf-8") as file:
                    content = file.read()

                entry_cmd = self._get_entry_command()
                split = self._extract_itemize_entries_section(content)
                if split is None:
                    return
                header, header_line, entries_section, footer = split

                entries, already_sorted, original_entry_count = self._collect_entries_for_sort(
                    entries_section, entry_cmd
                )
                if not entries:
                    if not silent:
                        self.ui.warning("No entries found to alphabetize.")
                    return
                if already_sorted:
                    if not silent:
                        self.ui.info("Entries are already alphabetized.", accent="dim")
                    return

                sorted_entries = sorted(entries, key=lambda x: x[0])
                if len(sorted_entries) != original_entry_count:
                    loss_count = original_entry_count - len(sorted_entries)
                    self.ui.error(
                        f"Entry count mismatch detected: {original_entry_count} entries before, "
                        f"{len(sorted_entries)} after ({loss_count} would be lost). "
                        "Aborting alphabetization to prevent data loss."
                    )
                    return

                sorted_entries_section = self._render_sorted_entries_section(
                    header_line,
                    entries_section,
                    sorted_entries,
                )
                sorted_content = header + sorted_entries_section + footer
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

    def _extract_itemize_entries_section(
        self, content: str
    ) -> Optional[Tuple[str, str, str, str]]:
        """Return (header, itemize_header_line, entries_section, footer)."""
        itemize_header_match = re.search(
            r"\\begin{itemize}\[[^\]]*leftmargin[^\]]*\]",
            content,
            re.IGNORECASE,
        )
        if not itemize_header_match:
            self.ui.error("Could not find the entries section.")
            return None

        entries_start = itemize_header_match.start()
        header_line = itemize_header_match.group(0)
        entries_end = content.find("\\end{itemize}", itemize_header_match.end())
        if entries_end == -1:
            self.ui.error("Could not find the end of the entries section.")
            return None

        header = content[:entries_start]
        entries_section = content[itemize_header_match.end() : entries_end]
        footer = content[entries_end:]
        return header, header_line, entries_section, footer

    def _collect_entries_for_sort(
        self,
        entries_section: str,
        entry_cmd: str,
    ) -> Tuple[List[Tuple[str, str, str, int, int]], bool, int]:
        parsed_entries = parse_all_entries(entries_section, entry_cmd)
        if not parsed_entries:
            return [], True, 0

        entries: List[Tuple[str, str, str, int, int]] = []
        already_sorted = True
        previous_key: Optional[str] = None
        for groups, start, end in parsed_entries:
            full_entry = entries_section[start:end]
            word = groups[0].strip()
            normalized = self.normalize_word(word)
            if previous_key is not None and normalized < previous_key:
                already_sorted = False
            previous_key = normalized
            entries.append((normalized, word, full_entry, start, end))

        return entries, already_sorted, len(parsed_entries)

    @staticmethod
    def _render_sorted_entries_section(
        header_line: str,
        entries_section: str,
        entries: List[Tuple[str, str, str, int, int]],
    ) -> str:
        slots = sorted(entries, key=lambda item: item[3])
        sorted_blocks = [entry for _, _, entry, _, _ in entries]

        rendered = [header_line]
        cursor = 0
        for index, slot in enumerate(slots):
            _normalized, _word, _entry, start, end = slot
            rendered.append(entries_section[cursor:start])
            rendered.append(sorted_blocks[index])
            cursor = end
        rendered.append(entries_section[cursor:])
        return "".join(rendered)

    def update_entry_in_file(self, word_capitalized: str, new_block: str) -> None:
        """Replace the LaTeX entry block for the given word with new_block.

        Uses balanced-brace parsing to correctly handle nested LaTeX macros.

        Raises:
            EntryNotFoundError: If the entry cannot be located in the file.
            IOError: If file read/write operations fail.
        """
        with file_lock(self.latex_file):
            with self.latex_file.open("r", encoding="utf-8") as f:
                content = f.read()

            entry_cmd = self._get_entry_command()
            bounds = find_entry_bounds(content, entry_cmd, word_capitalized, prefer_last=False)

            if bounds is None:
                raise EntryNotFoundError(
                    f"Could not locate LaTeX entry for '{word_capitalized}' in file. "
                    f"The entry may have been manually modified or deleted."
                )

            start, end = bounds
            new_content = content[:start] + new_block + content[end:]
            atomic_write_text(self.latex_file, new_content, create_backup=True)

    def _report_load_issues(self, issues: List[str]) -> None:
        for issue in issues:
            if issue in self._reported_load_issues:
                continue
            self._reported_load_issues.add(issue)
            self.ui.warning(issue)

    def _read_text_for_scan(self) -> Optional[str]:
        try:
            content = self.latex_file.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            self.ui.error(f"Error reading file: {exc}", with_panel=True)
            return None

        if "\ufffd" in content:
            self._report_load_issues(
                [f"Some characters in {self.latex_file} could not be decoded and were replaced."]
            )
        return content

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
        with file_lock(self.latex_file):
            # Merge planning must use the file state protected by this exact
            # transaction. Computing from a session cache before taking the
            # lock lets two successful merges silently overwrite each other.
            self.load_existing_entries()
            normalized = self.normalize_word(existing_word)
            key = self.normalized_entries.get(normalized, existing_word.lower())
            entry = self.word_entries.get(key)
            if not entry:
                self.ui.error(f"Cannot merge: existing entry for '{existing_word}' not found.")
                return False

            defs_existing = self._coerce_existing_definitions(entry)
            exs_existing = self._coerce_existing_examples(entry)
            merged_defs = self._dedup_merge_definitions(defs_existing, new_defs)
            merged_exs = self._dedup_merge_examples(exs_existing, new_examples)
            final_type = entry.get("type") or new_type
            latex_block = self.format_latex_entry(
                entry["word"],
                final_type,
                merged_defs,
                merged_exs,
                entry_command=self.entry_command,
            )

            if not self._replace_entry_block(entry["word"], latex_block):
                return False

            self.load_existing_entries()
            return True

    @staticmethod
    def _coerce_existing_definitions(entry: Dict[str, Any]) -> List[str]:
        defs_existing = entry.get("definitions_list")
        if defs_existing:
            return list(defs_existing)
        return [d.strip() for d in entry.get("definitions", "").split("; ") if d.strip()]

    def _coerce_existing_examples(self, entry: Dict[str, Any]) -> List[Tuple[str, str]]:
        exs_existing = entry.get("examples_list") or []
        if exs_existing:
            return list(exs_existing)
        examples_text = entry.get("examples")
        if examples_text:
            return self._parse_examples_string(examples_text)
        return []

    @staticmethod
    def normalize_text_for_merge(s: str) -> str:
        """Return the canonical text key used by repository merges."""
        text = re.sub(r"\s+", " ", s).strip().lower()
        return normalize_word_key(text)

    @classmethod
    def normalize_example_for_merge(
        cls,
        example: Tuple[str, str],
    ) -> Tuple[str, str]:
        """Return the canonical pair key used by repository merges."""
        return (
            cls.normalize_text_for_merge(example[0]),
            cls.normalize_text_for_merge(example[1]),
        )

    @classmethod
    def new_definitions_for_merge(
        cls,
        defs_existing: Sequence[str],
        new_defs: Sequence[str],
    ) -> List[str]:
        """Return genuinely new definitions in candidate order."""
        seen = {cls.normalize_text_for_merge(value) for value in defs_existing}
        additions: List[str] = []
        for definition in new_defs:
            normalized = cls.normalize_text_for_merge(definition)
            if normalized and normalized not in seen:
                seen.add(normalized)
                additions.append(definition)
        return additions

    @classmethod
    def new_examples_for_merge(
        cls,
        exs_existing: Sequence[Tuple[str, str]],
        new_examples: Sequence[Tuple[str, str]],
    ) -> List[Tuple[str, str]]:
        """Return genuinely new examples in candidate order."""
        seen = {cls.normalize_example_for_merge(value) for value in exs_existing}
        additions: List[Tuple[str, str]] = []
        for example in new_examples:
            normalized = cls.normalize_example_for_merge(example)
            if normalized not in seen:
                seen.add(normalized)
                additions.append(example)
        return additions

    @staticmethod
    def _norm_text_for_merge(s: str) -> str:
        """Backward-compatible private alias for the public merge normalizer."""
        return VocabRepository.normalize_text_for_merge(s)

    @classmethod
    def _dedup_merge_definitions(cls, defs_existing: List[str], new_defs: List[str]) -> List[str]:
        merged_map = {cls._norm_text_for_merge(d): d for d in defs_existing}
        for d in cls.new_definitions_for_merge(defs_existing, new_defs):
            merged_map[cls._norm_text_for_merge(d)] = d
        return list(merged_map.values())

    @classmethod
    def _dedup_merge_examples(
        cls,
        exs_existing: List[Tuple[str, str]],
        new_examples: List[Tuple[str, str]],
    ) -> List[Tuple[str, str]]:
        merged_map = {cls.normalize_example_for_merge(p): p for p in exs_existing}
        for p in cls.new_examples_for_merge(exs_existing, new_examples):
            merged_map[cls.normalize_example_for_merge(p)] = p
        return list(merged_map.values())

    def _replace_entry_block(self, word_capitalized: str, latex_block: str) -> bool:
        try:
            self.update_entry_in_file(word_capitalized, latex_block)
            return True
        except EntryNotFoundError as exc:
            self.ui.error(f"Merge failed: {exc}", with_panel=True)
        except IOError as exc:
            self.ui.error(f"Merge failed - file I/O error: {exc}", with_panel=True)
        return False

    @staticmethod
    def _update_entry_memory(
        entry: Dict[str, Any],
        final_type: str,
        merged_defs: List[str],
        merged_exs: List[Tuple[str, str]],
    ) -> None:
        entry["type"] = final_type
        entry["definitions_list"] = merged_defs
        entry["examples_list"] = merged_exs
        entry["definitions"] = "; ".join(merged_defs)
        entry["examples"] = "; ".join([f"{f} ({e})" for f, e in merged_exs])

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
            return _LATEX_ESCAPE_PATTERN.sub(lambda m: _LATEX_ESCAPE_MAPPING[m.group(0)], text)

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
