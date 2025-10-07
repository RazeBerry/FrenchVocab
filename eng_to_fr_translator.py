import re
import string
import unicodedata
from pathlib import Path
from typing import Dict, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

# Import LLMClient
from llm_client import LLMClient

# Import templates needed ONLY for initial file creation
from eng_to_fr_latex_templates import INITIAL_ENG_FR_TEX_CONTENT, FINAL_ENG_FR_TEX_CONTENT

# Define a dedicated, simple prompt for English-to-French translation
# Use a standard placeholder {} which will be filled by .format()
ENG_TO_FR_TRANSLATION_PROMPT_TEMPLATE = """Translate the following English text accurately into French. 
Provide only the resulting French translation, with no additional commentary, labels, or explanations.

English Text: "{english_text}"

French Translation:"""


class EnglishToFrenchTranslator:
    DEFAULT_FILENAME = "EnglishToFrench.tex"

    def __init__(
        self,
        console: Console,
        client: LLMClient,
        latex_file_path: Optional[Path] = None,
        prompt_template: str = ENG_TO_FR_TRANSLATION_PROMPT_TEMPLATE,
        initial_tex_content: str = INITIAL_ENG_FR_TEX_CONTENT,
        final_tex_content: str = FINAL_ENG_FR_TEX_CONTENT,
        default_filename: Optional[str] = None,
        source_label: str = "English",
        target_label: str = "French",
        ui_title: str = "English → French Translator",
        table_headers: Tuple[str, str] = ("English", "French"),
    ):
        """
        Initializes the EnglishToFrenchTranslator.

        Args:
            console: The rich Console object for UI.
            client: The initialized LLM client (implements stream method).
            latex_file_path: Path to the LaTeX file. Defaults to EnglishToFrench.tex in CWD.
        """
        self.console = console
        self.client = client
        self.prompt_template = prompt_template
        self.initial_tex_content = initial_tex_content
        self.final_tex_content = final_tex_content
        self.source_label = source_label
        self.target_label = target_label
        self.ui_title = ui_title
        self.table_headers = table_headers

        filename = default_filename or self.DEFAULT_FILENAME

        if latex_file_path is None:
            self.latex_file = Path.cwd() / filename
        else:
            self.latex_file = latex_file_path

        self.eng_fr_pairs: Dict[str, Dict[str, str]] = {}

        self._ensure_tex_file_exists()
        self.load_existing_entries()
        self.entry_count = len(self.eng_fr_pairs)

    def _ensure_tex_file_exists(self):
        """Checks if the LaTeX file exists, creates it if not."""
        if not self.latex_file.exists():
            self._create_initial_tex_file()

    def _create_initial_tex_file(self):
        """Creates the initial LaTeX file with preamble and structure."""
        try:
            self.latex_file.parent.mkdir(parents=True, exist_ok=True)
            with self.latex_file.open('w', encoding='utf-8') as file:
                file.write(self.initial_tex_content)
                file.write(self.final_tex_content)
            self.console.print(f"[bold green]Created initial LaTeX file: {self.latex_file}[/bold green]")
        except IOError as e:
            self.console.print(f"[bold red]Error creating initial LaTeX file {self.latex_file}: {e}[/bold red]")
            # Depending on severity, might want to raise or exit

    def load_existing_entries(self):
        """Loads existing English-French pairs from the LaTeX file."""
        if not self.latex_file.exists():
            self.console.print(f"[bold yellow]LaTeX file {self.latex_file} not found. Starting fresh.[/bold yellow]")
            return

        try:
            # Add errors='ignore' to handle potential encoding issues
            with self.latex_file.open("r", encoding="utf-8", errors='ignore') as file:
                content = file.read()
        except UnicodeDecodeError as e:
            self.console.print(f"[bold red]UnicodeDecodeError reading {self.latex_file}: {e}. Some characters might be lost.[/bold red]")
            return

        # Regex to find \\engfre{English}{French} entries
        # It handles potential curly braces within the arguments
        # Use a raw string literal to avoid escaping issues
        entry_pattern = re.compile(r"\\engfre\{(.*?)\}\{(.*?)\}", re.DOTALL)
        
        loaded_count = 0
        parse_errors = 0
        self.eng_fr_pairs.clear() # Clear before loading

        # Find all matches
        matches = entry_pattern.finditer(content)

        for match in matches:
            try:
                english_original = match.group(1).strip()
                french_translation = match.group(2).strip()

                if not english_original or not french_translation:
                   self.console.print(
                       f"[bold yellow]Skipping entry with empty {self.source_label} or {self.target_label} text near {match.start()}[/bold yellow]"
                   )
                   parse_errors += 1
                   continue

                normalized_english = self.normalize_english(english_original)

                if normalized_english in self.eng_fr_pairs:
                    self.console.print(f"[bold orange3]Warning: Duplicate normalized English key '{normalized_english}' found. Overwriting entry for '{self.eng_fr_pairs[normalized_english]['english']}' with '{english_original}'.[/bold orange3]")

                self.eng_fr_pairs[normalized_english] = {
                    'english': english_original,
                    'french': french_translation
                }
                loaded_count += 1

            except Exception as e: # Catch potential errors in processing a match
                self.console.print(f"[bold red]Error parsing entry near position {match.start()}: {e}[/bold red]")
                parse_errors += 1

        self.entry_count = len(self.eng_fr_pairs)
        pair_label = f"{self.source_label}-{self.target_label}"
        self.console.print(
            f"Loaded {self.entry_count} {pair_label} pairs from {self.latex_file}. ({parse_errors} parsing errors)"
        )


    def normalize_english(self, text: str) -> str:
        """Normalizes English text: lowercase, removes punctuation (keeps apostrophes)."""
        if not text:
            return ""
        text = text.lower().strip()
        # Remove punctuation except apostrophes
        text = text.translate(str.maketrans('', '', string.punctuation.replace("'", "")))
        # Normalize unicode characters (optional, but can help with consistency)
        text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def check_duplicate_english(self, normalized_english: str) -> Optional[Dict[str, str]]:
        """Checks if the normalized English text already exists."""
        return self.eng_fr_pairs.get(normalized_english)

    def display_duplicate_warning(self, existing_entry: Dict[str, str]):
        """Displays a warning that the English text already exists."""
        panel_content = (
            f"This {self.source_label} phrase already exists:\n\n"
            f"  [bold cyan]{self.source_label}:[/bold cyan] {existing_entry['english']}\n"
            f"  [bold magenta]{self.target_label}:[/bold magenta] {existing_entry['french']}"
        )
        self.console.print(Panel(panel_content, title="Duplicate Found", border_style="yellow", expand=False))

    def _collect_multiline_input(self, language_label: str) -> Optional[str]:
        """Collect multiline input, returning the joined text or None if cancelled."""
        instructions = (
            f"[cyan]Enter {language_label} text to translate.[/cyan]\n"
            "[dim]- Paste or type your text. Press Enter on an empty line to submit.\n"
            "- Enter 'q' on the first line to cancel.\n"
            "- After each line, the current text will be echoed so you can press Enter to finish without retyping.[/dim]"
        )
        self.console.print(Panel(instructions, border_style="blue", expand=False))

        lines = []
        first = True
        while True:
            try:
                prompt = (
                    f"\nEnter {language_label} text (or 'q' to cancel): "
                    if first
                    else "Enter additional text (leave blank to finish): "
                )
                line = input(prompt)
            except EOFError:
                break

            if first and line.strip().lower() == 'q':
                self.console.print("[yellow]Translation cancelled.[/yellow]")
                return None

            if not line and not first:
                break

            lines.append(line)
            first = False
            current_text = "\n".join(lines).strip()
            self.console.print(
                Panel(
                    f"[dim]Captured so far ({len(lines)} line(s)):[/dim] {current_text if current_text else '[empty]'}",
                    border_style="dim",
                    expand=False,
                )
            )

        text = "\n".join(lines).strip()
        if not text:
            self.console.print("[bold red]Input cannot be empty.[/bold red]")
            return None
        return text

    def get_english_input(self) -> Optional[str]:
        """Prompts the user for source-language input (supports multiline)."""
        while True:
            english_text = self._collect_multiline_input(self.source_label)
            if english_text is None:
                return None
            if english_text:
                return english_text

    def query_ai_for_translation(self, english_text: str) -> Optional[str]:
        """Queries the LLM for translation."""
        if not self.client:
            self.console.print("[bold red]LLM client not available.[/bold red]")
            return None

        # Use the new, dedicated prompt template
        prompt = self.prompt_template.format(english_text=english_text)

        try:
            with self.console.status("[cyan]Querying AI for translation..."):
                # Use the stream method from our LLMClient
                chunks = []
                for text in self.client.stream(prompt):
                    chunks.append(text)
                translation = "".join(chunks).strip()

            if translation:
                # Basic check to see if the response looks like a translation
                if len(translation) > 0 and english_text.lower() not in translation.lower():
                     return translation
                else:
                    self.console.print("[bold yellow]Warning: AI response might be empty or suspicious:[/bold yellow]")
                    self.console.print(f"> {translation}")
                    # Ask user if they want to accept this response?
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


    def _confirm_yes_no(self, message: str, default: bool = True) -> bool:
        """Prompt user for a yes/no answer accepting upper/lowercase responses."""
        default_choice = "y" if default else "n"
        prompt_text = f"{message} [y/n]"
        while True:
            response = Prompt.ask(prompt_text, default=default_choice)
            if response is None:
                response = default_choice
            normalized = response.strip().lower()
            if normalized in {"y", "yes"}:
                return True
            if normalized in {"n", "no"}:
                return False
            self.console.print("[bold yellow]Please enter Y or N.[/bold yellow]")

    def confirm_translation(self, english: str, french: str) -> bool:
        """Shows the translation and asks for user confirmation."""
        table = Table(title="Confirm Translation", show_header=False, box=None, padding=(0, 1))
        table.add_column(style="cyan", no_wrap=True)
        table.add_column(style="white")
        table.add_row(f"{self.source_label}:", english)
        table.add_row(f"{self.target_label}:", f"[bold green]{french}[/bold green]")

        self.console.print(Panel(table, border_style="blue", expand=False))
        return self._confirm_yes_no(
            f"Save this {self.source_label.lower()} → {self.target_label.lower()} translation?",
            default=True,
        )


    def _format_latex_entry(self, english: str, french: str) -> str:
        """Formats the English and French text into a LaTeX \\engfre command."""
        # Basic escaping for LaTeX special characters in user input
        def escape_latex(text: str) -> str:
            chars = {
                '&': r'\\&',
                '%': r'\\%',
                '$': r'\\$',
                '#': r'\\#',
                '_': r'\\_',
                '{': r'\\{',
                '}': r'\\}',
                '~': r'\\textasciitilde{}',
                '^': r'\\textasciicircum{}',
                '\\': r'\\textbackslash{}',
            }
            # Also handle potential issues with unbalanced braces if not escaped
            text = text.replace('{', r'\{').replace('}', r'\}')
            regex = re.compile('|'.join(re.escape(key) for key in sorted(chars.keys(), key = len, reverse=True)))
            return regex.sub(lambda match: chars[match.group(0)], text)

        escaped_english = escape_latex(english)
        escaped_french = escape_latex(french)
        return f"\\engfre{{{escaped_english}}}{{{escaped_french}}}"

    def _add_entry_to_file(self, latex_entry: str):
        """Inserts the new LaTeX entry into the .tex file before the final \\end{itemize}."""
        lines = []
        insert_line_index = -1

        try:
            # Read all existing lines
            with self.latex_file.open("r", encoding="utf-8") as file:
                lines = file.readlines()

            # Find the index of the last line containing \\end{itemize}
            for i in range(len(lines) - 1, -1, -1):
                if "\\end{itemize}" in lines[i]:
                    insert_line_index = i
                    break

            if insert_line_index == -1:
                # Fallback: if marker not found, find \\end{document} or append to end
                self.console.print("[bold yellow]Warning: Could not find \\end{itemize}. Trying to insert before \\end{document} or appending to end.[/bold yellow]")
                for i in range(len(lines) - 1, -1, -1):
                    if "\\end{document}" in lines[i]:
                        insert_line_index = i
                        break
                if insert_line_index == -1:
                    insert_line_index = len(lines) # Append to the very end if nothing else is found

            # Ensure the new entry has a newline
            if not latex_entry.endswith('\n'):
                latex_entry += '\n'
                
            # Add a preceding newline if the previous line wasn't empty or another entry
            if insert_line_index > 0 and lines[insert_line_index - 1].strip() and not lines[insert_line_index - 1].strip().startswith('\\engfre'):
                 latex_entry = '\n' + latex_entry

            # Insert the new entry into the list of lines
            lines.insert(insert_line_index, latex_entry)

            # Write the modified content back to the file
            with self.latex_file.open("w", encoding="utf-8") as file:
                file.writelines(lines)

        except FileNotFoundError:
            self.console.print(f"[bold red]Error: LaTeX file not found at {self.latex_file}. Cannot add entry.[/bold red]")
        except IOError as e:
            self.console.print(f"[bold red]Error writing to LaTeX file {self.latex_file}: {e}[/bold red]")
        except Exception as e:
             self.console.print(f"[bold red]An unexpected error occurred writing to file: {e}[/bold red]")


    def _add_entry_to_memory(self, english: str, french: str, normalized_key: str):
        """Adds the new entry to the in-memory dictionary."""
        self.eng_fr_pairs[normalized_key] = {'english': english, 'french': french}
        self.entry_count = len(self.eng_fr_pairs) # Update count

    def run_single_translation(self) -> bool:
        """Handles one full cycle: input -> check -> AI -> confirm -> save.

        Returns:
            bool: True if the user wants to translate another, False otherwise.
        """
        english_input = self.get_english_input()
        if english_input is None:
            return False # User cancelled

        normalized_english = self.normalize_english(english_input)
        existing_entry = self.check_duplicate_english(normalized_english)

        if existing_entry:
            self.display_duplicate_warning(existing_entry)
            # Ask if they want to translate another one anyway
            # return Confirm.ask("\nTranslate another phrase?", default=True)
            return False # Always return False to stop the loop

        # --- If new entry ---
        french_translation = self.query_ai_for_translation(english_input)
        if not french_translation:
             self.console.print("[yellow]Skipping this entry due to AI query failure or empty response.[/yellow]")
             # return Confirm.ask("\nTry translating another phrase?", default=True)
             return False # Always return False to stop the loop

        if self.confirm_translation(english_input, french_translation):
            latex_entry = self._format_latex_entry(english_input, french_translation)
            self._add_entry_to_file(latex_entry)
            self._add_entry_to_memory(english_input, french_translation, normalized_english)
            self.console.print("[bold green]Translation saved successfully![/bold green]")
        else:
            self.console.print("[yellow]Translation discarded.[/yellow]")

        # Ask to continue after saving or discarding
        # return Confirm.ask("\nTranslate another phrase?", default=True)
        return False # Always return False to stop the loop


    def run(self):
        """Main loop for the English-to-French translation feature."""
        self.console.print(Panel(
            f"[bold blue]{self.ui_title}[/bold blue]\nCurrently managing {self.entry_count} pairs in {self.latex_file.name}",
            border_style="blue"
        ))
        # Call run_single_translation only once
        self.run_single_translation()
        # while self.run_single_translation():
        #     pass # Loop continues as long as run_single_translation returns True
        self.console.print("Returning to main menu.")

    def display_all_pairs(self):
         """Displays all loaded English-French pairs in a table."""
         if not self.eng_fr_pairs:
             self.console.print(f"[bold yellow]No {self.source_label}-{self.target_label} pairs found.[/bold yellow]")
             return

         table = Table(title=f"All {self.source_label}-{self.target_label} Pairs ({self.entry_count} pairs)", expand=True)
         table.add_column("No.", style="cyan", justify="right", width=5)
         table.add_column(self.table_headers[0], style="green", ratio=1)
         table.add_column(self.table_headers[1], style="magenta", ratio=1)

         # Sort by normalized English key for consistent order
         sorted_pairs = sorted(self.eng_fr_pairs.items(), key=lambda item: item[0])

         for index, (norm_key, entry) in enumerate(sorted_pairs, 1):
             table.add_row(str(index), entry['english'], entry['french'])

         self.console.print(table)
         self.console.input("\nPress Enter to return...") # Pause screen


# Example usage (if run directly, for testing)
if __name__ == '__main__':
    import os
    from dotenv import load_dotenv

    load_dotenv() # Load .env file if present

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        print("Please create a .env file with ANTHROPIC_API_KEY='your-key' or set the environment variable.")
    else:
        try:
            test_client = LLMClient(api_key=api_key)
            # Perform a quick test call if needed to validate the key
            # test_client.messages.create(...) 
            console = Console()
            translator = EnglishToFrenchTranslator(console=console, client=test_client)
            # translator.display_all_pairs() # Uncomment to view existing pairs on start
            translator.run()
        except Exception as e:
             print(f"An error occurred during initialization: {e}") 
