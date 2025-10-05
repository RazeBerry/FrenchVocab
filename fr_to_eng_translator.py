import re
import string
import unicodedata
from pathlib import Path
from typing import Dict, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from llm_client import LLMClient
from fr_to_eng_latex_templates import INITIAL_FR_ENG_TEX_CONTENT, FINAL_FR_ENG_TEX_CONTENT, FR_TO_ENG_TRANSLATION_PROMPT_TEMPLATE

class FrenchToEnglishTranslator:
    DEFAULT_FILENAME = "FrenchToEnglish.tex"

    def __init__(self, console: Console, client: LLMClient, latex_file_path: Optional[Path] = None):
        self.console = console
        self.client = client

        if latex_file_path is None:
            self.latex_file = Path.cwd() / self.DEFAULT_FILENAME
        else:
            self.latex_file = latex_file_path

        self.fr_eng_pairs: Dict[str, Dict[str, str]] = {}

        self._ensure_tex_file_exists()
        self.load_existing_entries()
        self.entry_count = len(self.fr_eng_pairs)

    def _ensure_tex_file_exists(self):
        if not self.latex_file.exists():
            self._create_initial_tex_file()

    def _create_initial_tex_file(self):
        try:
            self.latex_file.parent.mkdir(parents=True, exist_ok=True)
            with self.latex_file.open('w', encoding='utf-8') as file:
                file.write(INITIAL_FR_ENG_TEX_CONTENT)
                file.write(FINAL_FR_ENG_TEX_CONTENT)
            self.console.print(f"[bold green]Created initial LaTeX file: {self.latex_file}[/bold green]")
        except IOError as e:
            self.console.print(f"[bold red]Error creating initial LaTeX file {self.latex_file}: {e}[/bold red]")

    def load_existing_entries(self):
        if not self.latex_file.exists():
            self.console.print(f"[bold yellow]LaTeX file {self.latex_file} not found. Starting fresh.[/bold yellow]")
            return

        try:
            with self.latex_file.open("r", encoding="utf-8", errors='ignore') as file:
                content = file.read()
        except UnicodeDecodeError as e:
            self.console.print(f"[bold red]UnicodeDecodeError reading {self.latex_file}: {e}.[/bold red]")
            return

        entry_pattern = re.compile(r"\\freeng\{(.*?)\}\{(.*?)\}", re.DOTALL)
        
        loaded_count = 0
        parse_errors = 0
        self.fr_eng_pairs.clear()

        matches = entry_pattern.finditer(content)

        for match in matches:
            try:
                french_original = match.group(1).strip()
                english_translation = match.group(2).strip()

                if not french_original or not english_translation:
                   self.console.print(f"[bold yellow]Skipping entry with empty French or English near {match.start()}[/bold yellow]")
                   parse_errors += 1
                   continue

                normalized_french = self.normalize_french(french_original)

                if normalized_french in self.fr_eng_pairs:
                    self.console.print(f"[bold orange3]Warning: Duplicate normalized French key '{normalized_french}' found. Overwriting.[/bold orange3]")

                self.fr_eng_pairs[normalized_french] = {
                    'french': french_original,
                    'english': english_translation
                }
                loaded_count += 1

            except Exception as e:
                self.console.print(f"[bold red]Error parsing entry near position {match.start()}: {e}[/bold red]")
                parse_errors += 1

        self.entry_count = len(self.fr_eng_pairs)
        self.console.print(f"Loaded {self.entry_count} French-English pairs from {self.latex_file}. ({parse_errors} errors)")

    def normalize_french(self, text: str) -> str:
        if not text:
            return ""
        text = text.lower().strip()
        text = text.translate(str.maketrans('', '', string.punctuation.replace("'", "")))
        text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def check_duplicate_french(self, normalized_french: str) -> Optional[Dict[str, str]]:
        return self.fr_eng_pairs.get(normalized_french)

    def display_duplicate_warning(self, existing_entry: Dict[str, str]):
        panel_content = (
            f"This French phrase already exists:\n\n"
            f"  [bold magenta]FR:[/bold magenta] {existing_entry['french']}\n"
            f"  [bold cyan]EN:[/bold cyan] {existing_entry['english']}"
        )
        self.console.print(Panel(panel_content, title="Duplicate Found", border_style="yellow", expand=False))

    def get_french_input(self) -> Optional[str]:
        while True:
            french_text = Prompt.ask("\nEnter the French text to translate (or 'q' to cancel)").strip()
            if french_text.lower() == 'q':
                self.console.print("[yellow]Translation cancelled.[/yellow]")
                return None
            if not french_text:
                self.console.print("[bold red]Input cannot be empty.[/bold red]")
            else:
                return french_text

    def query_ai_for_translation(self, french_text: str) -> Optional[str]:
        if not self.client:
            self.console.print("[bold red]LLM client not available.[/bold red]")
            return None

        prompt = FR_TO_ENG_TRANSLATION_PROMPT_TEMPLATE.format(french_text=french_text)

        try:
            with self.console.status("[cyan]Querying AI for translation..."):
                chunks = []
                generator = self.client.stream(prompt)
                for text in generator:
                    chunks.append(text)
                translation = "".join(chunks).strip()

            if translation:
                if len(translation) > 0 and french_text.lower() not in translation.lower():
                     return translation
                else:
                    self.console.print("[bold yellow]Warning: AI response might be empty or suspicious:[/bold yellow]")
                    self.console.print(f"> {translation}")
                    if Confirm.ask("Accept this response anyway?", default=False):
                         return translation
                    else:
                         return None
            else:
                self.console.print("[bold red]Error: Received empty response from AI.[/bold red]")
                return None

        except Exception as e:
            self.console.print(f"[bold red]An error occurred during AI query: {e}[/bold red]")
            return None

    def confirm_translation(self, french: str, english: str) -> bool:
        table = Table(title="Confirm Translation", show_header=False, box=None, padding=(0, 1), expand=True)
        table.add_column(style="magenta", no_wrap=True, width=10)
        table.add_column(style="white", no_wrap=False, overflow="fold")
        table.add_row("French:", french)
        table.add_row("English:", f"[bold green]{english}[/bold green]")

        self.console.print(Panel(table, border_style="blue", expand=True))
        return Confirm.ask("Save this translation?", default=True)

    def _format_latex_entry(self, french: str, english: str) -> str:
        def escape_latex(text: str) -> str:
            chars = {
                '&': r'\\&', '%': r'\\%', '$': r'\\$', '#': r'\\#', '_': r'\\_',
                '{': r'\\{', '}': r'\\}', '~': r'\\textasciitilde{}',
                '^': r'\\textasciicircum{}', '\\': r'\\textbackslash{}',
            }
            text = text.replace('{', r'\{').replace('}', r'\}')
            regex = re.compile('|'.join(re.escape(key) for key in sorted(chars.keys(), key=len, reverse=True)))
            return regex.sub(lambda match: chars[match.group(0)], text)

        escaped_french = escape_latex(french)
        escaped_english = escape_latex(english)
        return f"\\freeng{{{escaped_french}}}{{{escaped_english}}}"

    def _add_entry_to_file(self, latex_entry: str):
        lines = []
        insert_line_index = -1

        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                lines = file.readlines()

            for i, line in reversed(list(enumerate(lines))):
                if "\\end{itemize}" in line:
                    insert_line_index = i
                    break
            
            if insert_line_index != -1:
                lines.insert(insert_line_index, f"{latex_entry}\n\n")
                with self.latex_file.open("w", encoding="utf-8") as file:
                    file.writelines(lines)
                self.console.print(f"[green]Successfully added entry to {self.latex_file}[/green]")
            else:
                self.console.print("[bold red]Error: Could not find insertion point in LaTeX file.[/bold red]")

        except IOError as e:
            self.console.print(f"[bold red]Error writing to {self.latex_file}: {e}[/bold red]")

    def _add_entry_to_memory(self, french: str, english: str, normalized_key: str):
        self.fr_eng_pairs[normalized_key] = {'french': french, 'english': english}
        self.entry_count = len(self.fr_eng_pairs)

    def run_single_translation(self) -> bool:
        """Run a single translation. Returns False if user cancelled, True if translation completed."""
        french_text = self.get_french_input()
        if not french_text:
            return False # User cancelled

        normalized_french = self.normalize_french(french_text)
        existing_entry = self.check_duplicate_french(normalized_french)

        if existing_entry:
            self.display_duplicate_warning(existing_entry)
            return True

        english_translation = self.query_ai_for_translation(french_text)
        if not english_translation:
            return True

        if self.confirm_translation(french_text, english_translation):
            latex_entry = self._format_latex_entry(french_text, english_translation)
            self._add_entry_to_file(latex_entry)
            self._add_entry_to_memory(french_text, english_translation, normalized_french)
            self.console.print("[bold green]Translation saved![/bold green]")
        else:
            self.console.print("[yellow]Save cancelled.[/yellow]")
        
        return True

    def translate_and_save(self, french_text: str) -> bool:
        """Translate provided French text and save without prompting for input.

        Returns False only if user cancels at confirmation step or translation fails.
        """
        if not french_text:
            return False

        normalized_french = self.normalize_french(french_text)
        existing_entry = self.check_duplicate_french(normalized_french)

        if existing_entry:
            self.display_duplicate_warning(existing_entry)
            return True

        english_translation = self.query_ai_for_translation(french_text)
        if not english_translation:
            return False

        if self.confirm_translation(french_text, english_translation):
            latex_entry = self._format_latex_entry(french_text, english_translation)
            self._add_entry_to_file(latex_entry)
            self._add_entry_to_memory(french_text, english_translation, normalized_french)
            self.console.print("[bold green]Translation saved![/bold green]")
            return True
        else:
            self.console.print("[yellow]Save cancelled.[/yellow]")
            return False

    def run(self):
        self.console.print(Panel(
            "[bold blue]French -> English Translator[/bold blue]\nEnter French phrases to translate. Type 'q' to return to the main menu at any time.",
            title="Translator Mode",
            border_style="blue"
        ))
        while True:
            # Directly ask for a translation. If the user quits, break the loop.
            if not self.run_single_translation():
                break

    def display_all_pairs(self):
        if not self.fr_eng_pairs:
            self.console.print("[yellow]No saved French-English pairs found.[/yellow]")
            return

        table = Table(title=f"All French-English Pairs ({self.entry_count})", expand=True)
        table.add_column("French", style="magenta", max_width=50)
        table.add_column("English", style="cyan", max_width=50)
        
        sorted_pairs = sorted(self.fr_eng_pairs.values(), key=lambda p: self.normalize_french(p['french']))

        for pair in sorted_pairs:
            table.add_row(pair['french'], pair['english'])
            
        self.console.print(table) 
