"""Shared translator CLI implementation."""

from __future__ import annotations

import re
import string
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich import box

from vocab_builder.compat import runtime_root
from vocab_builder.languages import TranslatorConfig
from vocab_builder.llm_client import LLMClient
from vocab_builder.ui_helper import UIHelper, read_line
from vocab_builder.core.history_logger import TranslationLogger
from vocab_builder.core.file_safety import atomic_copy_file, atomic_write_text, file_lock
from vocab_builder.latex_repository import parse_balanced_group


@dataclass(frozen=True)
class TranslationDraft:
    source_text: str
    target_text: str
    normalized_key: str
    suspicious: bool = False
    dropped_fragment: Optional[str] = None
    existing_entry: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class TranslationSaveResult:
    status: str
    source_text: str
    target_text: str
    existing_entry: Optional[Dict[str, str]] = None


class TranslatorCLI:
    """Generic CLI translator parameterised by language configuration."""

    def __init__(
        self,
        console: Console,
        client: Optional[LLMClient],
        config: TranslatorConfig,
        latex_file_path: Optional[Path] = None,
        direction: str = "eng_to_target",
        logger: Optional[TranslationLogger] = None,
        usage_callback: Optional[Callable[[Dict[str, int]], None]] = None,
        on_query_exception: Optional[Callable[[Exception, str], bool]] = None,
    ) -> None:
        self.console = console
        self.ui = UIHelper(console)
        self.client = client
        self.config = config
        self.direction = direction
        self.logger = logger
        self.usage_callback = usage_callback
        self.on_query_exception = on_query_exception

        self.prompt_template = config.prompt_template
        self.prompt_variable = config.prompt_variable
        self.source_label = config.source_label
        self.target_label = config.target_label
        self.ui_title = config.ui_title
        self.table_headers = config.table_headers
        self.latex_commands = tuple(config.latex_commands or ())
        self.initial_tex_content = config.initial_tex_content
        self.final_tex_content = config.final_tex_content

        filename = config.default_filename
        if latex_file_path is None:
            source_root = Path(__file__).resolve().parent.parent.parent
            self.latex_file = runtime_root(source_root, create=True) / filename
        else:
            self.latex_file = latex_file_path

        self._pairs: Dict[str, Dict[str, str]] = {}
        self._entries_loaded = False

        self._ensure_tex_file_exists()

    # ------------------------------------------------------------------
    # Lazy loading
    # ------------------------------------------------------------------
    def _ensure_entries_loaded(self) -> None:
        """Load entries from LaTeX file on first access."""
        if not self._entries_loaded:
            self.load_existing_entries()
            self._entries_loaded = True

    @property
    def pairs(self) -> Dict[str, Dict[str, str]]:
        """Dictionary of translation pairs, loaded lazily on first access."""
        self._ensure_entries_loaded()
        return self._pairs

    @pairs.setter
    def pairs(self, value: Dict[str, Dict[str, str]]) -> None:
        """Allow direct assignment for backwards compatibility."""
        self._pairs = value
        self._entries_loaded = True

    @property
    def entry_count(self) -> int:
        """Number of loaded translation pairs."""
        self._ensure_entries_loaded()
        return len(self._pairs)

    @entry_count.setter
    def entry_count(self, value: int) -> None:
        """No-op setter for backwards compatibility; entry_count is computed from pairs."""
        pass

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------
    def _ensure_tex_file_exists(self) -> None:
        with file_lock(self.latex_file):
            if self.latex_file.exists():
                return
            backup_path = self._backup_path()
            if backup_path.exists() and backup_path.is_file():
                self._restore_from_backup_if_available()
                return
            self._create_initial_tex_file_unlocked()

    def _backup_path(self) -> Path:
        return self.latex_file.with_suffix(self.latex_file.suffix + ".bak")

    def _restore_from_backup_if_available(self) -> bool:
        backup_path = self._backup_path()
        if not backup_path.exists() or not backup_path.is_file():
            return False
        try:
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

    def _create_initial_tex_file(self) -> None:
        with file_lock(self.latex_file):
            if self.latex_file.exists():
                self.ui.warning(f"Initial LaTeX file already exists; leaving it unchanged: {self.latex_file}")
                return
            self._create_initial_tex_file_unlocked()

    def _create_initial_tex_file_unlocked(self) -> None:
        try:
            self.latex_file.parent.mkdir(parents=True, exist_ok=True)
            with self.latex_file.open("x", encoding="utf-8") as file:
                file.write(self.initial_tex_content)
                file.write(self.final_tex_content)
            self.ui.success(f"Created initial LaTeX file: {self.latex_file}")
        except FileExistsError:
            self.ui.warning(f"Initial LaTeX file already exists; leaving it unchanged: {self.latex_file}")
        except IOError as exc:
            self.ui.error(f"Failed to create initial LaTeX file {self.latex_file}: {exc}", with_panel=True)

    def load_existing_entries(self) -> None:
        if not self.latex_file.exists():
            self.ui.warning(f"LaTeX file {self.latex_file} not found. Starting fresh.")
            return

        try:
            with self.latex_file.open("r", encoding="utf-8", errors="replace") as file:
                content = file.read()
            # Check if replacement characters were inserted
            if '\ufffd' in content:
                self.ui.warning(
                    f"Some characters in {self.latex_file} could not be decoded and were replaced."
                )
        except IOError as exc:
            self.ui.error(
                f"Cannot read {self.latex_file}: {exc}",
                with_panel=True
            )
            return

        self._pairs.clear()
        loaded_count = 0
        parse_errors = 0

        # Use balanced-brace parsing for robust entry extraction
        for cmd in self.latex_commands:
            cmd_escaped = cmd if cmd.startswith('\\') else f'\\{cmd}'
            count, errors = self._parse_entries_for_command(content, cmd_escaped)
            loaded_count += count
            parse_errors += errors

        pair_count = len(self._pairs)
        summary = (
            f"Loaded {pair_count} {self.source_label}-{self.target_label} pairs from {self.latex_file}."
        )
        if parse_errors:
            summary += f" ({parse_errors} parsing errors)"
        self.ui.debug(summary)

    def _parse_entries_for_command(self, content: str, cmd: str) -> tuple:
        """Parse entries for a specific LaTeX command using balanced-brace parsing.

        Returns (loaded_count, parse_errors).
        """
        loaded_count = 0
        parse_errors = 0
        i = 0
        n = len(content)

        while i < n:
            # Find next occurrence of the command
            j = content.find(cmd, i)
            if j == -1:
                break
            if self._command_is_in_latex_comment(content, j):
                i = j + len(cmd)
                continue

            pos = j + len(cmd)
            # Skip whitespace to first brace
            while pos < n and content[pos].isspace():
                pos += 1

            if pos >= n or content[pos] != '{':
                i = j + len(cmd)
                continue

            try:
                # Parse first group (source)
                source, pos = parse_balanced_group(content, pos)
                source = source.strip()

                # Skip whitespace to second brace
                while pos < n and content[pos].isspace():
                    pos += 1

                if pos >= n or content[pos] != '{':
                    parse_errors += 1
                    i = j + len(cmd)
                    continue

                # Parse second group (target)
                target, pos = parse_balanced_group(content, pos)
                target = target.strip()

                if not source or not target:
                    self.ui.warning(
                        f"Skipping entry with empty {self.source_label} or {self.target_label} near position {j}."
                    )
                    parse_errors += 1
                    i = pos
                    continue

                normalized = self.normalize_text(source)
                pair_key = normalized
                if normalized in self._pairs:
                    existing = self._pairs[normalized]["source"]
                    self.ui.warning(
                        f"Duplicate normalized {self.source_label} key '{normalized}' found. "
                        f"Preserving both '{existing}' and '{source}'."
                    )
                    pair_key = self._unique_pair_key(normalized)

                entry = {"source": source, "target": target}
                if pair_key != normalized:
                    entry["duplicate_of"] = normalized
                self._pairs[pair_key] = entry
                loaded_count += 1
                i = pos

            except ValueError as exc:
                self.ui.error(f"Error parsing entry near position {j}: {exc}")
                parse_errors += 1
                i = j + len(cmd)

        return loaded_count, parse_errors

    def _unique_pair_key(self, normalized: str) -> str:
        suffix = 2
        while True:
            candidate = f"{normalized}__duplicate_{suffix}"
            if candidate not in self._pairs:
                return candidate
            suffix += 1

    @staticmethod
    def _command_is_in_latex_comment(content: str, command_pos: int) -> bool:
        """Return True when a command occurrence is after an unescaped % on its line."""
        line_start = content.rfind("\n", 0, command_pos) + 1
        prefix = content[line_start:command_pos]
        for index, char in enumerate(prefix):
            if char != "%":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and prefix[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                return True
        return False

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_text(text: str) -> str:
        if not text:
            return ""
        text = text.lower().strip()
        remove = string.punctuation.replace("'", "")
        text = text.translate(str.maketrans("", "", remove))
        text = "".join(
            char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
        )
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def check_duplicate(self, normalized_key: str) -> Optional[Dict[str, str]]:
        return self.pairs.get(normalized_key)

    def display_duplicate_warning(self, existing_entry: Dict[str, str]) -> None:
        # Warning panel: wrapped for inline alerts
        panel_content = (
            f"This {self.source_label} phrase already exists:\n\n"
            f"  [bold #E67E50]{self.source_label}:[/bold #E67E50] {existing_entry['source']}\n"
            f"  [bold magenta]{self.target_label}:[/bold magenta] {existing_entry['target']}"
        )
        self.ui.panel(
            panel_content,
            title="Duplicate Found",
            border_style="yellow3",
            box_style=box.ROUNDED,
        )

    def _collect_multiline_input(self) -> Optional[str]:
        # Instructions panel: wrapped for contextual info
        instructions = (
            "[#E67E50]Enter text to translate.[/#E67E50]\n"
            "[dim]- Type or paste your text, then press Enter.\n"
            "- Press Esc to cancel.[/dim]"
        )
        self.ui.panel(
            instructions,
            border_style="dark_orange",
            box_style=box.ROUNDED,
        )

        try:
            line = read_line("Text (Esc to cancel): ")
        except EOFError:
            self.ui.warning("Translation cancelled.")
            return None
        except KeyboardInterrupt:
            self.ui.warning("Translation cancelled.")
            return None

        # Detect ESC sequence and cancel
        if line and "\x1b" in line:
            self.ui.warning("Translation cancelled via Esc.")
            return None

        text = line.strip()
        if not text:
            self.ui.warning("Translation cancelled.")
            return None
        return text

    def get_source_input(self) -> Optional[str]:
        while True:
            text = self._collect_multiline_input()
            if text is None:
                return None
            if text:
                return text

    # ------------------------------------------------------------------
    # AI interaction
    # ------------------------------------------------------------------
    def query_ai_for_translation(
        self,
        source_text: str,
        *,
        confirm_suspicious: bool = True,
    ) -> Optional[str]:
        if not self.client:
            self.ui.error("Cannot query translation: LLM client not available.", with_panel=True)
            return None

        try:
            prompt = self.prompt_template.format(**{self.prompt_variable: source_text})
        except KeyError as exc:
            self.ui.error(f"Prompt template missing placeholder for '{exc.args[0]}'.")
            return None

        metrics: Dict[str, Any] = {}
        try:
            with self.console.status("[cyan]Querying AI for translation..."):
                chunks = []
                stream = self.client.stream(prompt, thinking_level="low")
                while True:
                    try:
                        chunk = next(stream)
                        chunks.append(chunk)
                    except StopIteration as stop:
                        metrics = stop.value if stop.value else {}
                        break
                translation = self._strip_translation_scaffolding("".join(chunks))
                self._emit_usage(metrics.get("usage") if isinstance(metrics, dict) else None)

            if not translation:
                self.ui.error("Error: received empty response from AI.")
                return None

            if source_text.lower() in translation.lower() and confirm_suspicious:
                self.ui.warning("AI response might be empty or suspicious:")
                self.ui.info(f"> {translation}", accent="dim")
                if not self.ui.confirm("Accept this response anyway?", default=False):
                    return None

            return translation

        except Exception as exc:  # pragma: no cover - defensive path
            handled = False
            if self.on_query_exception:
                provider_label = self._provider_label() or self.ui_title
                handled = self.on_query_exception(exc, provider_label)
            if not handled:
                self.ui.error(f"An error occurred during AI query: {exc}")
            return None
        finally:
            if not metrics:
                self._emit_usage(None)

    def confirm_translation(self, source_text: str, target_text: str) -> bool:
        # Confirmation preview: rendered without borders for easy copy/paste
        header = Text("Confirm Translation", style="bold #E67E50")
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(style="dark_orange", no_wrap=True)
        table.add_column(style="white")
        table.add_row(f"{self.source_label}:", Text(source_text))
        table.add_row(f"{self.target_label}:", Text(target_text, style="bold #51cf66"))

        self.console.print()
        self.console.print(header)
        self.console.print(table)
        self.console.print()
        return self.ui.confirm(
            f"Save this {self.source_label} → {self.target_label} translation?",
            default=True,
        )

    @staticmethod
    def _detect_truncated_input(
        text: str, *, threshold_chars: int = 80
    ) -> tuple:
        """Detect suspected mid-word truncation in long pasted input.

        Returns (sanitized_text, dropped_fragment). When dropped_fragment is
        None, no truncation was detected and the input is unchanged. Inputs
        shorter than threshold_chars or ending in sentence-final punctuation,
        whitespace, or a closing quote/bracket are passed through.
        """
        if not text:
            return text, None
        if text != text.rstrip():
            return text.rstrip(), None
        if len(text) < threshold_chars:
            return text, None
        if re.search(r"[.!?…»\"'\)\]\}”“:;]\s*$", text):
            return text, None
        if not text[-1].isalpha():
            return text, None
        last_ws = max(text.rfind(" "), text.rfind("\n"), text.rfind("\t"))
        if last_ws == -1:
            return text, None
        trimmed = text[:last_ws].rstrip()
        fragment = text[last_ws:].strip()
        if not trimmed or not fragment:
            return text, None
        return trimmed, fragment

    def _strip_translation_scaffolding(self, raw: str) -> str:
        """Remove prompt-template labels and trailing Notes blocks from raw output.

        The directional translator prompts ask the model to emit
        "<Lang> translation: ..." and an optional "Notes (optional): ..." block.
        Persisting those labels into the .tex file is a parser bug; this method
        is the single chokepoint that cleans them out before save.
        """
        if not raw:
            return ""
        text = raw.strip()

        label_words = {self.source_label, self.target_label, "German", "English", "French"}
        label_alt = "|".join(
            sorted({re.escape(w) for w in label_words if w}, key=len, reverse=True)
        )
        leading_label = re.compile(
            rf"^\s*(?:(?:{label_alt})\s+)?translation\s*:\s*",
            re.IGNORECASE,
        )
        text = leading_label.sub("", text, count=1)

        notes_block = re.compile(
            r"(?:^|\n)[ \t]*notes?\s*(?:\(optional\))?\s*:.*\Z",
            re.IGNORECASE | re.DOTALL,
        )
        text = notes_block.sub("", text)

        return text.strip()

    @staticmethod
    def _escape_latex(text: str) -> str:
        replacements = {
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
            "\\": r"\textbackslash{}",
        }
        regex = re.compile("|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True)))
        return regex.sub(lambda match: replacements[match.group(0)], text)

    def _format_latex_entry(self, source_text: str, target_text: str) -> str:
        src = self._escape_latex(source_text)
        tgt = self._escape_latex(target_text)
        command = self.latex_commands[0] if self.latex_commands else "pair"
        return f"\\{command}{{{src}}}{{{tgt}}}"

    def _add_entry_to_file(self, latex_entry: str) -> bool:
        try:
            with file_lock(self.latex_file):
                with self.latex_file.open("r", encoding="utf-8") as file:
                    content = file.read()

                insert_pos = content.rfind("\\end{itemize}")
                if insert_pos == -1:
                    self.ui.error("Error: could not find insertion point in LaTeX file.")
                    return False

                updated = content[:insert_pos] + f"{latex_entry}\n\n" + content[insert_pos:]

                atomic_write_text(self.latex_file, updated, create_backup=True)

            self.ui.success(f"Added entry to {self.latex_file}")
            return True

        except OSError as exc:
            self.ui.error(f"Error writing to {self.latex_file}: {exc}")
            return False

    def _add_entry_to_memory(self, source_text: str, target_text: str, normalized_key: str) -> None:
        self._ensure_entries_loaded()
        self._pairs[normalized_key] = {"source": source_text, "target": target_text}

    def _emit_usage(self, usage: Optional[Dict[str, int]]) -> None:
        if self.usage_callback and usage:
            self.usage_callback(usage)

    def _provider_label(self) -> Optional[str]:
        if not self.client:
            return None
        getter = getattr(self.client, "model_label", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return self.client.__class__.__name__
        return self.client.__class__.__name__

    def _log_saved_translation(
        self,
        source_text: str,
        target_text: str,
        normalized_key: str,
        *,
        operation_id: Optional[str] = None,
    ) -> bool:
        if not self.logger or not self.logger.enabled:
            return True
        try:
            if operation_id and self.logger.has_operation(
                operation_id,
                flow="translator",
            ):
                return True
            return self.logger.log_translator_entry(
                direction=self.direction,
                source_text=source_text,
                target_text=target_text,
                normalized_key=normalized_key,
                provider=self._provider_label(),
                latex_file=self.latex_file,
                source_label=self.source_label,
                target_label=self.target_label,
                metadata=(
                    {"surface": "mobile", "operation_id": operation_id}
                    if operation_id
                    else None
                ),
            )
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------
    def run_single_translation(self) -> bool:
        source_text = self.get_source_input()
        if not source_text:
            return False
        return self.translate_and_save(source_text)

    def translate_and_save(self, source_text: str, *, provided_translation: Optional[str] = None) -> bool:
        if not source_text:
            return False

        draft = self.preview_translation(
            source_text,
            provided_translation=provided_translation,
            confirm_suspicious=True,
        )
        if draft is None:
            return False
        if draft.existing_entry:
            self.display_duplicate_warning(draft.existing_entry)
            return True
        if not self.confirm_translation(draft.source_text, draft.target_text):
            self.ui.warning("Save cancelled.")
            return False
        return self.save_translation(draft).status in {"saved", "duplicate"}

    def preview_translation(
        self,
        source_text: str,
        *,
        provided_translation: Optional[str] = None,
        confirm_suspicious: bool = False,
    ) -> Optional[TranslationDraft]:
        """Generate the same translation result without requesting a save."""
        if not source_text or not source_text.strip():
            return None
        source_text = source_text.strip()
        sanitized, dropped_fragment = self._detect_truncated_input(source_text)
        if dropped_fragment is not None:
            source_text = sanitized

        normalized = self.normalize_text(source_text)
        self._entries_loaded = False
        existing_entry = self.check_duplicate(normalized)
        if existing_entry:
            return TranslationDraft(
                source_text=source_text,
                target_text=existing_entry["target"],
                normalized_key=normalized,
                dropped_fragment=dropped_fragment,
                existing_entry=dict(existing_entry),
            )

        target_text = (
            provided_translation.strip()
            if provided_translation is not None
            else self.query_ai_for_translation(
                source_text,
                confirm_suspicious=confirm_suspicious,
            )
        )
        if not target_text:
            return None
        return TranslationDraft(
            source_text=source_text,
            target_text=target_text,
            normalized_key=normalized,
            suspicious=source_text.casefold() in target_text.casefold(),
            dropped_fragment=dropped_fragment,
        )

    def save_translation(
        self,
        draft: TranslationDraft,
        *,
        operation_id: Optional[str] = None,
    ) -> TranslationSaveResult:
        """Commit a confirmed draft with the CLI's locked duplicate recheck."""
        with file_lock(self.latex_file):
            self._entries_loaded = False
            self._ensure_entries_loaded()
            existing_entry = self.check_duplicate(draft.normalized_key)
            if existing_entry:
                return TranslationSaveResult(
                    status="duplicate",
                    source_text=draft.source_text,
                    target_text=existing_entry["target"],
                    existing_entry=dict(existing_entry),
                )

            latex_entry = self._format_latex_entry(
                draft.source_text,
                draft.target_text,
            )
            if not self._add_entry_to_file(latex_entry):
                return TranslationSaveResult(
                    status="failed",
                    source_text=draft.source_text,
                    target_text=draft.target_text,
                )
            self._add_entry_to_memory(
                draft.source_text,
                draft.target_text,
                draft.normalized_key,
            )
            self._log_saved_translation(
                draft.source_text,
                draft.target_text,
                draft.normalized_key,
                operation_id=operation_id,
            )
            self.ui.success("Translation saved successfully!")
            return TranslationSaveResult(
                status="saved",
                source_text=draft.source_text,
                target_text=draft.target_text,
            )

    def repair_translation_history(
        self,
        draft: TranslationDraft,
        *,
        operation_id: str,
    ) -> bool:
        """Idempotently finish mobile history after a committed file write."""
        return self._log_saved_translation(
            draft.source_text,
            draft.target_text,
            draft.normalized_key,
            operation_id=operation_id,
        )

    # ------------------------------------------------------------------
    # Compatibility helpers
    # ------------------------------------------------------------------
    def _confirm_yes_no(self, message: str, default: bool = True) -> bool:
        """Backward-compatible confirm helper retained for legacy tests."""
        if not hasattr(self, "ui") or self.ui is None:
            console = getattr(self, "console", Console())
            self.ui = UIHelper(console)

        default_choice = "y" if default else "n"
        yes_tokens = {"y", "yes", "ja", "j", "oui", "o", "1", "true"}
        no_tokens = {"n", "no", "nein", "non", "0", "false"}

        while True:
            try:
                response = read_line(f"{message} [y/n] ", console=self.console)
            except (EOFError, OSError):
                response = Prompt.ask(
                    f"{message} [y/n]",
                    default=default_choice,
                    show_default=False,
                )
            if response is None:
                response = ""
            normalized = (response.strip() or default_choice).casefold()
            if normalized in yes_tokens:
                return True
            if normalized in no_tokens:
                return False
            self.ui.warning("Please enter Y or N.")

    def run(self) -> None:
        # Header panel: full-width for major section indicator
        header = (
            f"[bold #E67E50]{self.ui_title}[/bold #E67E50]\n"
            f"Currently managing {self.entry_count} pairs in {self.latex_file.name}"
        )
        self.ui.panel(
            header,
            border_style="dark_orange",
            title="Translator Mode",
            expand=True,
            box_style=box.ROUNDED,
        )
        self.run_single_translation()

        # Quick action menu - allow users to continue without returning to main menu
        while True:
            try:
                quick_action = self.ui.interactive_menu(
                    "What's next?",
                    [
                        ("another", "Translate another sentence"),
                        ("view", "View all translations"),
                        ("menu", "Return to main menu"),
                    ],
                    "Press Esc to return to main menu",
                )
            except KeyboardInterrupt:
                break  # User pressed Esc

            if quick_action == "another":
                self.run_single_translation()
            elif quick_action == "view":
                self.display_all_pairs()
            else:  # "menu"
                break

    def display_all_pairs(self) -> None:
        if not self.pairs:
            self.ui.warning(f"No {self.source_label}-{self.target_label} pairs found.")
            return

        rows = [
            [str(index), entry["source"], entry["target"]]
            for index, (_, entry) in enumerate(sorted(self.pairs.items()), 1)
        ]

        self.ui.render_table(
            title=f"All {self.source_label}-{self.target_label} Pairs ({self.entry_count})",
            columns=["No.", self.table_headers[0], self.table_headers[1]],
            rows=rows,
            column_styles=["cyan", "green", "magenta"],
        )
        read_line("\nPress Enter to return...")
