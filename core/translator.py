"""Shared translator CLI implementation."""

from __future__ import annotations

import re
import string
import unicodedata
from pathlib import Path
from typing import Dict, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from languages import TranslatorConfig
from llm_client import LLMClient


class TranslatorCLI:
    """Generic CLI translator parameterised by language configuration."""

    def __init__(
        self,
        console: Console,
        client: Optional[LLMClient],
        config: TranslatorConfig,
        latex_file_path: Optional[Path] = None,
    ) -> None:
        self.console = console
        self.client = client
        self.config = config

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
            self.console.print(
                f"[bold green]Created initial LaTeX file: {self.latex_file}[/bold green]"
            )
        except IOError as exc:
            self.console.print(
                f"[bold red]Error creating initial LaTeX file {self.latex_file}: {exc}[/bold red]"
            )

    def load_existing_entries(self) -> None:
        if not self.latex_file.exists():
            self.console.print(
                f"[bold yellow]LaTeX file {self.latex_file} not found. Starting fresh.[/bold yellow]"
            )
            return

        try:
            with self.latex_file.open("r", encoding="utf-8", errors="ignore") as file:
                content = file.read()
        except UnicodeDecodeError as exc:
            self.console.print(
                f"[bold red]UnicodeDecodeError reading {self.latex_file}: {exc}. Some characters might be lost.[/bold red]"
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
                    self.console.print(
                        f"[bold yellow]Skipping entry with empty {self.source_label} or {self.target_label} near {match.start()}[/bold yellow]"
                    )
                    parse_errors += 1
                    continue

                normalized = self.normalize_text(source)
                if normalized in self.pairs:
                    existing = self.pairs[normalized]["source"]
                    self.console.print(
                        f"[bold orange3]Warning: Duplicate normalized {self.source_label} key '{normalized}' found."
                        f" Overwriting entry for '{existing}' with '{source}'.[/bold orange3]"
                    )

                self.pairs[normalized] = {"source": source, "target": target}
                loaded_count += 1
            except Exception as exc:  # pragma: no cover - defensive path
                self.console.print(
                    f"[bold red]Error parsing entry near position {match.start()}: {exc}[/bold red]"
                )
                parse_errors += 1

        self.entry_count = len(self.pairs)
        self.console.print(
            f"Loaded {self.entry_count} {self.source_label}-{self.target_label} pairs from {self.latex_file}. ({parse_errors} parsing errors)"
        )

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
        panel_content = (
            f"This {self.source_label} phrase already exists:\n\n"
            f"  [bold cyan]{self.source_label}:[/bold cyan] {existing_entry['source']}\n"
            f"  [bold magenta]{self.target_label}:[/bold magenta] {existing_entry['target']}"
        )
        self.console.print(Panel(panel_content, title="Duplicate Found", border_style="yellow", expand=False))

    def _collect_multiline_input(self, language_label: str) -> Optional[str]:
        instructions = (
            f"[cyan]Enter {language_label} text to translate.[/cyan]\n"
            "[dim]- Paste or type your text. Press Enter on an empty line to submit.\n"
            "- Enter 'q' on the first line to cancel.\n"
            "- After each line, the current text will be echoed so you can simply press Enter to finish.[/dim]"
        )
        self.console.print(Panel(instructions, border_style="blue", expand=False))

        lines = []
        first = True
        try:
            while True:
                prompt = (
                    f"\nEnter {language_label} text (or 'q' to cancel): "
                    if first
                    else "Enter additional text (leave blank to finish): "
                )
                line = input(prompt)

                if first and line.strip().lower() == "q":
                    self.console.print("[yellow]Translation cancelled.[/yellow]")
                    return None

                if not line and not first:
                    break

                lines.append(line)
                first = False

                current_text = "\n".join(lines).strip()
                display = Text()
                display.append(f"Captured so far ({len(lines)} line(s)):\n", style="dim")
                display.append(current_text if current_text else "[empty]")
                self.console.print(
                    Panel(
                        display,
                        border_style="dim",
                        expand=False,
                    )
                )
        except EOFError:
            pass

        text = "\n".join(lines).strip()
        if not text:
            self.console.print("[bold red]Input cannot be empty.[/bold red]")
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
            self.console.print("[bold red]LLM client not available.[/bold red]")
            return None

        try:
            prompt = self.prompt_template.format(**{self.prompt_variable: source_text})
        except KeyError as exc:
            self.console.print(
                f"[bold red]Prompt template missing placeholder for '{exc.args[0]}'.[/bold red]"
            )
            return None

        try:
            with self.console.status("[cyan]Querying AI for translation..."):
                chunks = []
                for chunk in self.client.stream(prompt):
                    chunks.append(chunk)
                translation = "".join(chunks).strip()

            if not translation:
                self.console.print("[bold red]Error: Received empty response from AI.[/bold red]")
                return None

            if source_text.lower() in translation.lower():
                self.console.print(
                    "[bold yellow]Warning: AI response might be empty or suspicious:[/bold yellow]"
                )
                self.console.print(f"> {translation}")
                if not Confirm.ask("Accept this response anyway?", default=False):
                    return None

            return translation

        except Exception as exc:  # pragma: no cover - defensive path
            self.console.print(f"[bold red]An error occurred during AI query: {exc}[/bold red]")
            return None

    # ------------------------------------------------------------------
    # Confirmation & persistence
    # ------------------------------------------------------------------
    def _confirm_yes_no(self, message: str, default: bool = True) -> bool:
        default_choice = "y" if default else "n"
        prompt_text = f"{message} [y/n]: "
        yes_tokens = {"y", "yes", "ja", "j", "oui", "o", "1", "true"}
        no_tokens = {"n", "no", "nein", "non", "0", "false"}

        while True:
            response = self.console.input(prompt_text)
            if response is None:
                response = ""
            normalized = response.strip() or default_choice
            normalized = normalized.casefold()
            if normalized in yes_tokens:
                return True
            if normalized in no_tokens:
                return False
            self.console.print("[bold yellow]Please enter Y or N.[/bold yellow]")

    def confirm_translation(self, source_text: str, target_text: str) -> bool:
        table = Table(title="Confirm Translation", show_header=False, box=None, padding=(0, 1))
        table.add_column(style="cyan", no_wrap=True)
        table.add_column(style="white")
        table.add_row(f"{self.source_label}:", Text(source_text))
        table.add_row(f"{self.target_label}:", Text(target_text, style="bold green"))

        self.console.print(Panel(table, border_style="blue", expand=False))
        return self._confirm_yes_no(
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
                self.console.print(
                    "[bold red]Error: Could not find insertion point in LaTeX file.[/bold red]"
                )
                return

            lines.insert(insert_index, f"{latex_entry}\n\n")
            with self.latex_file.open("w", encoding="utf-8") as file:
                file.writelines(lines)

            self.console.print(
                f"[green]Successfully added entry to {self.latex_file}[/green]"
            )

        except IOError as exc:
            self.console.print(f"[bold red]Error writing to {self.latex_file}: {exc}[/bold red]")

    def _add_entry_to_memory(self, source_text: str, target_text: str, normalized_key: str) -> None:
        self.pairs[normalized_key] = {"source": source_text, "target": target_text}
        self.entry_count = len(self.pairs)

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
            self.console.print(
                "[yellow]Skipping this entry due to AI query failure or empty response.[/yellow]"
            )
            return False

        if self.confirm_translation(source_text, target_text):
            latex_entry = self._format_latex_entry(source_text, target_text)
            self._add_entry_to_file(latex_entry)
            self._add_entry_to_memory(source_text, target_text, normalized)
            self.console.print("[bold green]Translation saved successfully![/bold green]")
        else:
            self.console.print("[yellow]Translation discarded.[/yellow]")

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
            self.console.print("[bold green]Translation saved successfully![/bold green]")
            return True

        self.console.print("[yellow]Save cancelled.[/yellow]")
        return False

    def run(self) -> None:
        self.console.print(
            Panel(
                f"[bold blue]{self.ui_title}[/bold blue]\nCurrently managing {self.entry_count} pairs in {self.latex_file.name}",
                border_style="blue",
                title="Translator Mode",
            )
        )
        self.run_single_translation()
        self.console.print("Returning to main menu.")

    def display_all_pairs(self) -> None:
        if not self.pairs:
            self.console.print(
                f"[bold yellow]No {self.source_label}-{self.target_label} pairs found.[/bold yellow]"
            )
            return

        table = Table(
            title=f"All {self.source_label}-{self.target_label} Pairs ({self.entry_count})",
            expand=True,
        )
        table.add_column("No.", style="cyan", justify="right", width=5)
        table.add_column(self.table_headers[0], style="green", ratio=1)
        table.add_column(self.table_headers[1], style="magenta", ratio=1)

        for index, (key, entry) in enumerate(sorted(self.pairs.items()), 1):
            table.add_row(str(index), entry["source"], entry["target"])

        self.console.print(table)
        self.console.input("\nPress Enter to return...")
