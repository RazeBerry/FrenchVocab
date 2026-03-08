"""Shared translator CLI implementation."""

from __future__ import annotations

import re
import string
import unicodedata
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
from vocab_builder.latex_repository import parse_balanced_group


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
        if not self.latex_file.exists():
            self._create_initial_tex_file()

    def _create_initial_tex_file(self) -> None:
        try:
            self.latex_file.parent.mkdir(parents=True, exist_ok=True)
            with self.latex_file.open("w", encoding="utf-8") as file:
                file.write(self.initial_tex_content)
                file.write(self.final_tex_content)
            self.ui.success(f"Created initial LaTeX file: {self.latex_file}")
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
                if normalized in self._pairs:
                    existing = self._pairs[normalized]["source"]
                    self.ui.warning(
                        f"Duplicate normalized {self.source_label} key '{normalized}' found. "
                        f"Overwriting entry for '{existing}' with '{source}'."
                    )

                self._pairs[normalized] = {"source": source, "target": target}
                loaded_count += 1
                i = pos

            except ValueError as exc:
                self.ui.error(f"Error parsing entry near position {j}: {exc}")
                parse_errors += 1
                i = j + len(cmd)

        return loaded_count, parse_errors

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
    def query_ai_for_translation(self, source_text: str) -> Optional[str]:
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
                stream = self.client.stream(prompt, thinking_level="medium")
                while True:
                    try:
                        chunk = next(stream)
                        chunks.append(chunk)
                    except StopIteration as stop:
                        metrics = stop.value if stop.value else {}
                        break
                translation = "".join(chunks).strip()
                self._emit_usage(metrics.get("usage") if isinstance(metrics, dict) else None)

            if not translation:
                self.ui.error("Error: received empty response from AI.")
                return None

            if source_text.lower() in translation.lower():
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
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            insert_pos = content.rfind("\\end{itemize}")
            if insert_pos == -1:
                self.ui.error("Error: could not find insertion point in LaTeX file.")
                return False

            updated = content[:insert_pos] + f"{latex_entry}\n\n" + content[insert_pos:]

            from vocab_builder.core.file_safety import atomic_write_text
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

    def _log_saved_translation(self, source_text: str, target_text: str, normalized_key: str) -> None:
        if not self.logger or not self.logger.enabled:
            return
        try:
            self.logger.log_translator_entry(
                direction=self.direction,
                source_text=source_text,
                target_text=target_text,
                normalized_key=normalized_key,
                provider=self._provider_label(),
                latex_file=self.latex_file,
                source_label=self.source_label,
                target_label=self.target_label,
            )
        except Exception:
            pass

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

        normalized = self.normalize_text(source_text)
        existing_entry = self.check_duplicate(normalized)
        if existing_entry:
            self.display_duplicate_warning(existing_entry)
            return True

        if provided_translation is not None:
            target_text = provided_translation.strip()
        else:
            target_text = self.query_ai_for_translation(source_text)
        if not target_text:
            return False

        if self.confirm_translation(source_text, target_text):
            latex_entry = self._format_latex_entry(source_text, target_text)
            if not self._add_entry_to_file(latex_entry):
                return False
            self._add_entry_to_memory(source_text, target_text, normalized)
            self._log_saved_translation(source_text, target_text, normalized)
            self.ui.success("Translation saved successfully!")
            return True

        self.ui.warning("Save cancelled.")
        return False

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
