import re
from typing import List, Tuple, Optional, Dict
import os
import unicodedata
import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress
from rich.prompt import Prompt, Confirm

try:
    client = anthropic.Anthropic(
        api_key=os.environ['ANTHROPIC_API_KEY']
    )
except KeyError:
    print("ANTHROPIC_API_KEY environment variable is not set.")
    exit(1)
# Initialize Rich console
console = Console()


class FrenchVocabBuilder:
    def __init__(self, latex_file: str):
        self.latex_file = latex_file
        self.max_word_length = 30
        self.word_entries: Dict[str, Dict] = {}
        self.normalized_entries: Dict[str, str] = {}  # Add this line
        self.console = Console()
        self.load_existing_entries()
        # Initialize LiveSearch
        self.normalized_entries = {}
        self.load_existing_entries()
        self.entry_count = self.count_entries()  # Initialize entry count

    def count_entries(self) -> int:
        try:
            with open(self.latex_file, "r", encoding="utf-8") as file:
                content = file.read()
            return len(re.findall(r"\\entry\{", content))
        except FileNotFoundError:
            console.print(f"[bold red]Error: File not found - {self.latex_file}[/bold red]")
            return 0
        except IOError as e:
            console.print(f"[bold red]Error reading file: {e}[/bold red]")
            return 0
    def load_existing_entries(self):
        with open(self.latex_file, "r", encoding="utf-8") as file:
            content = file.read()

        entries = re.findall(
            r"\\entry\{(\w+)\}\{(.*?)\}\s*\{(.*?)\}\s*\{(.*?)\}", content, re.DOTALL
        )
        for word, word_type, definitions, examples in entries:
            self.word_entries[word.lower()] = {
                "word": word,
                "type": word_type,
                "definitions": definitions.strip(),
                "examples": examples.strip(),
            }

        # Print all extracted entries
        console.print("[bold blue]Entries extracted in load_existing_entries:")
        for word, entry in self.word_entries.items():
            normalized_word = self.normalize_word(word)
            self.normalized_entries[normalized_word] = word

    def normalize_word(self, word: str) -> str:
        word = word.lower().strip()
        return ''.join(c for c in unicodedata.normalize('NFD', word) if unicodedata.category(c) != 'Mn')

    def check_duplicate(self, word: str) -> Optional[str]:
        normalized_word = self.normalize_word(word)
        return self.normalized_entries.get(normalized_word)

    def handle_duplicate(self, word: str, existing_word: str) -> bool:
        console.print(f"[bold yellow]Warning: '{word}' already exists as '{existing_word}'.[/bold yellow]")
        choice = Prompt.ask("Choose an action", choices=["s", "v", "f"], default="s")
        if choice == "s":
            return False
        elif choice == "v":
            self.display_existing_entry(existing_word)
            return False
        else:
            return True

    def display_existing_entry(self, word: str):
        entry = self.word_entries[word.lower()]
        self.display_parsed_info(entry['word'], [entry['type']], entry['definitions'].split('; '),
                                 [tuple(e.split(' (', 1)) for e in entry['examples'].split('; ')])

    def welcome_screen(self):
        console.print(
            Panel.fit(
                f"[bold blue]Welcome to the French Vocabulary LaTeX Builder![/bold blue]\n\n"
                f"This application helps you build a LaTeX document for French vocabulary.\n"
                f"You can input French words, and the AI will provide definitions and examples.\n\n"
                f"[bold green]Your current vocabulary library contains {self.entry_count} words.[/bold green]",
                title="French Vocab Builder",
                border_style="bold green",
            )
        )


    def show_menu(self):
        console.print("\n[bold cyan]Menu Options:[/bold cyan]")
        console.print("1. Add a new word")
        console.print("2. Exit")
        console.print(f"[bold green]Current word count: {self.entry_count}[/bold green]")
        choice = Prompt.ask("Choose an option", choices=["1", "2"])
        return choice

    from rich.table import Table

    def generate_table(self, search_term: str, results: dict) -> Table:
        table = Table(title=f"Search Results for: {search_term}")
        table.add_column("Word", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Definitions", style="green")

        for word, entry in results.items():
            table.add_row(
                entry["word"],
                entry["type"],
                (
                    entry["definitions"][:50] + "..."
                    if len(entry["definitions"]) > 50
                    else entry["definitions"]
                ),
            )

        return table


    def get_word_input(self) -> str:
        while True:
            word = Prompt.ask("\nEnter a French word or short expression")
            word = word.strip()

            if len(word.split()) > 5:
                console.print(
                    "[bold red]Error: Please enter a single word or short expression (max 5 words).[/bold red]"
                )
            elif len(word) > self.max_word_length:
                console.print(
                    f"[bold red]Error: Input is too long. Please limit to {self.max_word_length} characters.[/bold red]"
                )
            elif not word:
                console.print("[bold red]Error: Input cannot be empty.[/bold red]")
            else:
                return word

    def query_ai(self, word: str) -> str:
        prompt = f"""
        Please provide information for the French word or expression "{word}" in the following format, do note, if a user enters an English word or an expression, you are translate it into French to the best of your ability and then do the following. Furthermore if the user were to enter a verb, YOU ARE TO automatically conjugate it into standard infinitive form:
        Correctly Spelt Word: WORD 
        Word Type: [Specify the word type without any additional symbols or marks. Choose from: noun, verb, adjective, expression, adverb, pronominal verb, or use your discretion for other types]
        Definitions:
        a. [First English definition]
        b. [Second English definition]
        c. [Third English definition (if applicable)]
        Examples:
        1. [French example 1]
        [English translation 1]
        2. [French example 2]
        [English translation 2]
        3. [French example 3 (if applicable)]
        [English translation 3 (if applicable)]
Apply the following criteria:
1. Always convert French verbs to their standard infinitive form, regardless of how they're initially conjugated.
2. For the Word Type, use only natural language without any additional symbols or marks.
3. Provide detailed and nuanced English definitions for each entry.

When creating definitions and examples:
- Ensure that the definitions are comprehensive and capture different nuances of the word's meaning.
- Provide context-rich examples that demonstrate the word's usage in various situations.
- Make sure the English translations accurately reflect the meaning and tone of the French examples.
        """

        with Progress() as progress:
            task = progress.add_task("[cyan]Querying AI...", total=100)

            try:
                message = client.messages.create(
                    model="claude-3-5-sonnet-20240620",
                    max_tokens=8192,
                    temperature=0,
                    messages=[
                        {"role": "user", "content": [{"type": "text", "text": prompt}]}
                    ],
                    extra_headers={
                        "anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15"
                    },
                )
                progress.update(task, advance=100)
                return message.content[0].text
            except anthropic.APIError as e:
                console.print(f"[bold red]Error querying AI: {e}[/bold red]")
                return ""

    def parse_ai_response(
        self, response: str
    ) -> Tuple[str, List[str], List[Tuple[str, str]]]:
        """
        Parse the AI's response to extract word type, definitions, and examples.

        Args:
            response (str): The AI's response string.

        Returns:
            Tuple[str, List[str], List[Tuple[str, str]]]: A tuple containing:
                - word type (str)
                - list of definitions (List[str])
                - list of examples, each a tuple of (French, English) (List[Tuple[str, str]])
        """
        # Extract word type
        word_type_match = re.search(r"Word Type:\s*(.*?)\nDefinitions:", response, re.DOTALL)
        if word_type_match:
            word_type_string = word_type_match.group(1).strip()
            word_type = [word_type_string]  # Treat as a single-item list
        else:
            word_type = ["Unknown"]

        # Extract definitions
        definitions_match = re.search(
            r"Definitions:(.*?)Examples:", response, re.DOTALL
        )
        if definitions_match:
            definitions_text = definitions_match.group(1)
            definitions = [
                d.strip() for d in re.findall(r"[a-z]\.\s*(.*)", definitions_text)
            ]
        else:
            definitions = []

        # Extract examples
        examples_match = re.search(r"Examples:(.*)", response, re.DOTALL)
        if examples_match:
            examples_text = examples_match.group(1)
            examples = re.findall(
                r"(\d+\.\s*(.*?)\n\s*(.*?)(?=\n\d+\.|\Z))", examples_text, re.DOTALL
            )
            examples = [
                (french.strip(), english.strip().strip("[]"))
                for _, french, english in examples
            ]
        else:
            examples = []

        return word_type, definitions, examples

    def format_latex_entry(
        self,
        word: str,
        word_type: str,
        definitions: List[str],
        examples: List[Tuple[str, str]],
    ) -> str:
        """
        Format the word information into a LaTeX entry.

        Args:
            word (str): The French word.
            word_type (str): The type of the word (e.g., noun, verb).
            definitions (List[str]): List of definitions for the word.
            examples (List[Tuple[str, str]]): List of example tuples (French, English).

        Returns:
            str: Formatted LaTeX entry for the word.
        """
        # Capitalize the word
        capitalized_word = word.capitalize()

        def_items = "".join([f"    \\item {d}\n" for d in definitions])
        example_items = "".join(
            [f"    \\item {e[0]} \\\\ ({e[1]})\n" for e in examples]
        )

        latex_entry = f"""\\entry{{{capitalized_word}}}{{{word_type}}}
      {{
    {def_items.rstrip()}
      }}
      {{
    {example_items.rstrip()}
      }}"""

        # Remove all square brackets using regex
        latex_entry = re.sub(r"\[|\]", "", latex_entry)

        return latex_entry

    def insert_entry_alphabetically(self, new_entry: str, new_word: str) -> None:
        try:
            with open(self.latex_file, "r", encoding="utf-8") as file:
                content = file.read()

            normalized_new_word = self.normalize_word(new_word)
            if normalized_new_word in self.normalized_entries:
                existing_word = self.normalized_entries[normalized_new_word]
                console.print(
                    f"[bold yellow]Entry for '{new_word}' already exists as '{existing_word}'. Updating entry.[/bold yellow]")

                # Remove existing entry
                existing_entry_pattern = re.compile(rf"\\entry{{{re.escape(existing_word)}}}.*?(?=\\entry|\Z)",
                                                    re.DOTALL)
                content = existing_entry_pattern.sub('', content)

            # Find the position to insert the new entry
            insert_position = content.rfind("\\entry")
            insert_position = content.find("\\end{itemize}", insert_position)

            # Insert the new entry
            updated_content = (
                    content[:insert_position]
                    + new_entry
                    + "\n\n"
                    + content[insert_position:]
            )

            with open(self.latex_file, "w", encoding="utf-8") as file:
                file.write(updated_content)

            console.print(f"[bold green]Added/Updated entry for '{new_word}' in {self.latex_file}[/bold green]")

            # Update the normalized entries dictionary
            self.normalized_entries[normalized_new_word] = new_word.capitalize()

            # Alphabetize entries after insertion
            self.alphabetize_entries()

        except FileNotFoundError:
            console.print(f"[bold red]Error: File not found - {self.latex_file}[/bold red]")
        except IOError as e:
            console.print(f"[bold red]Error reading from or writing to file: {e}[/bold red]")

    def alphabetize_entries(self) -> None:
        try:
            with open(self.latex_file, "r", encoding="utf-8") as file:
                content = file.read()

            # Find the start and end of the entries section
            entries_start = content.find("\\begin{itemize}[leftmargin=*]")
            entries_end = content.rfind("\\end{itemize}")

            if entries_start == -1 or entries_end == -1:
                console.print("[bold red]Error: Could not find the entries section.[/bold red]")
                return

            # Split the content into header, entries, and footer
            header = content[:entries_start]
            entries_section = content[entries_start:entries_end]
            footer = content[entries_end:]

            # Extract all \entry blocks
            entry_pattern = r"(\\entry\{.*?\}.*?(?=\\entry|\Z))"
            entries = re.findall(entry_pattern, entries_section, re.DOTALL)

            if not entries:
                console.print("[bold yellow]No entries found to alphabetize.[/bold yellow]")
                return

            # Sort entries based on the word (first argument of \entry)
            sorted_entries = sorted(
                entries,
                key=lambda x: re.search(r"\\entry\{(.*?)\}", x).group(1).lower()
            )

            # Reconstruct the entries section
            sorted_entries_section = "\\begin{itemize}[leftmargin=*]\n" + "".join(sorted_entries)

            # Reconstruct the file content
            sorted_content = header + sorted_entries_section + footer

            # Safeguard: Check if we're not accidentally removing a large portion of the content
            if len(sorted_content) < len(content) * 0.9:  # If we've lost more than 10% of content
                console.print(
                    "[bold red]Warning: Significant content loss detected. Aborting alphabetization.[/bold red]")
                return

            # Write the sorted content back to the file
            with open(self.latex_file, "w", encoding="utf-8") as file:
                file.write(sorted_content)

            console.print("[bold green]Entries alphabetized successfully.[/bold green]")

        except FileNotFoundError:
            console.print(f"[bold red]Error: File not found - {self.latex_file}[/bold red]")
        except IOError as e:
            console.print(f"[bold red]Error reading from or writing to file: {e}[/bold red]")


    def exit_screen(self):
        console.print(
            Panel.fit(
                "[bold blue]Thank you for using the French Vocabulary LaTeX Builder![/bold blue]\n\n"
                "Your LaTeX file has been updated with the new entries.",
                title="Goodbye!",
                border_style="bold green",
            )
        )

    def remove_accents(self, input_str):
        nfkd_form = unicodedata.normalize("NFKD", input_str)
        return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

    def run(self):
        self.welcome_screen()
        while True:
            self.entry_count = self.count_entries()  # Update count at the start of each loop
            choice = self.show_menu()
            if choice == "1":
                word = self.get_word_input()
                existing_word = self.check_duplicate(word)
                if existing_word:
                    if not self.handle_duplicate(word, existing_word):
                        continue
                ai_response = self.query_ai(word)
                if ai_response:
                    word_type, definitions, examples = self.parse_ai_response(ai_response)
                    self.display_parsed_info(word, word_type, definitions, examples)

                    corrected_spelling_match = re.search(r'Correctly Spelt Word:\s*(.*)', ai_response)
                    corrected_spelling = corrected_spelling_match.group(1) if corrected_spelling_match else None

                    if corrected_spelling and corrected_spelling.lower() != word.lower():
                        if Confirm.ask(f"Did you mean '{corrected_spelling}' instead of '{word}'?"):
                            word = corrected_spelling

                    latex_entry = self.format_latex_entry(word, word_type, definitions, examples)
                    self.display_latex_entry(latex_entry)
                    self.insert_entry_alphabetically(latex_entry, word.capitalize())

                    self.word_entries[word.lower()] = {
                        "word": word.capitalize(),
                        "type": word_type,
                        "definitions": "; ".join(definitions),
                        "examples": "; ".join([f"{f} ({e})" for f, e in examples]),
                    }

                    self.alphabetize_entries()
                else:
                    self.console.print(
                        f"[bold red]Failed to get information for '{word}'. Skipping this entry.[/bold red]")
            elif choice == "2":
                self.exit_screen()
                break
            self.console.input("\nPress Enter to continue...")

    def display_parsed_info(
            self,
            word: str,
            word_type: List[str],  # Explicitly type word_type as a List
            definitions: List[str],
            examples: List[Tuple[str, str]],
    ):
        table = Table(
            title=f"Information for [bold green]{word.capitalize()}[/bold green]"
        )
        table.add_column("Category", style="cyan", no_wrap=True)
        table.add_column("Information", style="magenta")

        # Convert word_type list to a string
        word_type_str = ", ".join(word_type)
        table.add_row("Word Type", word_type_str)

        def_str = "\n".join([f"• {d}" for d in definitions])
        table.add_row("Definitions", def_str)

        ex_str = "\n".join([f"• {f}\n  ({e})" for f, e in examples])
        table.add_row("Examples", ex_str)

        console.print(table)

    def display_latex_entry(self, latex_entry: str):
        console.print(
            Panel(latex_entry, title="Generated LaTeX Entry", border_style="bold blue")
        )

def main() -> None:
    """
    Main function to run the French vocabulary builder.

    This function creates an instance of FrenchVocabBuilder and runs it.
    """
    latex_file = "/Users/sihao/Documents/LaTeX Files/FrenchVocab.tex"
    app = FrenchVocabBuilder(latex_file)
    app.run()


if __name__ == "__main__":
    main()
