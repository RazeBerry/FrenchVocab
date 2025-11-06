"""Shared translator CLI implementation."""

from __future__ import annotations

import re
import string
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich import box

from languages import TranslatorConfig
from llm_client import LLMClient
from ui_helper import UIHelper, read_line
from core.history_logger import TranslationLogger


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
    ) -> None:
        self.console = console
        self.ui = UIHelper(console)
        self.client = client
        self.config = config
        self.direction = direction
        self.logger = logger
        self.usage_callback = usage_callback

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
        self.latex_file = latex_file_path if latex_file_path is not None else Path.cwd() / filename

        self.pairs: Dict[str, Dict[str, str]] = {}

        self._ensure_tex_file_exists()
        self.load_existing_entries()
        self.entry_count = len(self.pairs)

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
            with self.latex_file.open("r", encoding="utf-8", errors="ignore") as file:
                content = file.read()
        except UnicodeDecodeError as exc:
            self.ui.error(
                f"Cannot read {self.latex_file}: UnicodeDecodeError {exc}. Some characters might be lost.",
                with_panel=True
            )
            return

        commands_pattern = "|".join(re.escape(cmd) for cmd in self.latex_commands)
        entry_pattern = re.compile(rf"\\(?:{commands_pattern})\{{(.*?)\}}\{{(.*?)\}}", re.DOTALL)

        self.pairs.clear()
        loaded_count = 0
        parse_errors = 0

        for match in entry_pattern.finditer(content):
            try:
                source = match.group(1).strip()
                target = match.group(2).strip()
                if not source or not target:
                    self.ui.warning(
                        f"Skipping entry with empty {self.source_label} or {self.target_label} near position {match.start()}."
                    )
                    parse_errors += 1
                    continue

                normalized = self.normalize_text(source)
                if normalized in self.pairs:
                    existing = self.pairs[normalized]["source"]
                    self.ui.warning(
                        f"Duplicate normalized {self.source_label} key '{normalized}' found."
                        f" Overwriting entry for '{existing}' with '{source}'."
                    )

                self.pairs[normalized] = {"source": source, "target": target}
                loaded_count += 1
            except Exception as exc:  # pragma: no cover - defensive path
                self.ui.error(f"Error parsing entry near position {match.start()}: {exc}")
                parse_errors += 1

        self.entry_count = len(self.pairs)
        summary = (
            f"Loaded {self.entry_count} {self.source_label}-{self.target_label} pairs from {self.latex_file}."
        )
        if parse_errors:
            summary += f" ({parse_errors} parsing errors)"
        self.ui.info(summary)

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
            expand=False,
            box_style=box.ROUNDED,
        )

    def _collect_multiline_input(self, language_label: str) -> Optional[str]:
        # Instructions panel: wrapped for contextual info
        instructions = (
            f"[#E67E50]Enter {language_label} text to translate.[/#E67E50]\n"
            "[dim]- Type or paste your text.\n"
            "- Enter 'q' on the first line to cancel.\n"
            "- Press Enter on an empty line to finish.[/dim]"
        )
        self.ui.panel(
            instructions,
            border_style="dark_orange",
            expand=False,
            box_style=box.ROUNDED,
        )

        lines: list[str] = []

        while True:
            prompt = (
                f"{language_label} text (or 'q' to cancel): "
                if not lines
                else "Add more text (press Enter to finish): "
            )

            try:
                line = read_line(prompt)
            except EOFError:
                break

            if not lines:
                stripped = line.strip()
                if stripped.lower() == "q":
                    self.ui.warning("Translation cancelled.")
                    return None
                if not stripped:
                    self.ui.warning("Please enter at least one line (or 'q' to cancel).")
                    continue
            else:
                if line == "":
                    break

            lines.append(line.rstrip("\n"))
            plural = "line" if len(lines) == 1 else "lines"
            self.ui.info(f"Captured {len(lines)} {plural}. Blank line to finish.", accent="dim")

        if not lines:
            self.ui.warning("Translation cancelled.")
            return None

        text = "\n".join(lines).strip()
        if not text:
            self.ui.error("Cannot continue: input cannot be empty.")
            return None
        return text

    def get_source_input(self) -> Optional[str]:
        while True:
            text = self._collect_multiline_input(self.source_label)
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
                stream = self.client.stream(prompt)
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

    def _add_entry_to_file(self, latex_entry: str) -> None:
        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                lines = file.readlines()

            insert_index = -1
            for idx, line in reversed(list(enumerate(lines))):
                if "\\end{itemize}" in line:
                    insert_index = idx
                    break

            if insert_index == -1:
                self.ui.error("Error: could not find insertion point in LaTeX file.")
                return

            lines.insert(insert_index, f"{latex_entry}\n\n")
            with self.latex_file.open("w", encoding="utf-8") as file:
                file.writelines(lines)

            self.ui.success(f"Added entry to {self.latex_file}")

        except IOError as exc:
            self.ui.error(f"Error writing to {self.latex_file}: {exc}")

    def _add_entry_to_memory(self, source_text: str, target_text: str, normalized_key: str) -> None:
        self.pairs[normalized_key] = {"source": source_text, "target": target_text}
        self.entry_count = len(self.pairs)

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

        normalized = self.normalize_text(source_text)
        existing_entry = self.check_duplicate(normalized)

        if existing_entry:
            self.display_duplicate_warning(existing_entry)
            return False

        target_text = self.query_ai_for_translation(source_text)
        if not target_text:
            self.ui.warning("Skipping this entry due to AI query failure or empty response.")
            return False

        if self.confirm_translation(source_text, target_text):
            latex_entry = self._format_latex_entry(source_text, target_text)
            self._add_entry_to_file(latex_entry)
            self._add_entry_to_memory(source_text, target_text, normalized)
            self._log_saved_translation(source_text, target_text, normalized)
            self.ui.success("Translation saved successfully!")
        else:
            self.ui.warning("Translation discarded.")

        return False

    def translate_and_save(self, source_text: str) -> bool:
        if not source_text:
            return False

        normalized = self.normalize_text(source_text)
        existing_entry = self.check_duplicate(normalized)
        if existing_entry:
            self.display_duplicate_warning(existing_entry)
            return True

        target_text = self.query_ai_for_translation(source_text)
        if not target_text:
            return False

        if self.confirm_translation(source_text, target_text):
            latex_entry = self._format_latex_entry(source_text, target_text)
            self._add_entry_to_file(latex_entry)
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
        self.ui.info("Returning to main menu.")

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
