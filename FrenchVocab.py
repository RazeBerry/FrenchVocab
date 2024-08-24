import json
import os
import random
import re
import unicodedata
from typing import List, Tuple, Optional, Dict
import sys
import anthropic
import genanki
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.table import Table
from enum import Enum, auto
from latex_templates import INITIAL_TEX_CONTENT, SAMPLE_ENTRY, FINAL_TEX_CONTENT
import time
import threading

console = Console()


class WordType(Enum):
    NOUN = auto()
    VERB = auto()
    ADJECTIVE = auto()
    ADVERB = auto()
    EXPRESSION = auto()
    PRONOMINAL_VERB = auto()
    OTHER = auto()


class FrenchVocabBuilder:
    DEFAULT_FILENAME = "FrenchVocab.tex"
    def __init__(self, latex_file: str):
        init_start = time.time()
        
        self.console = Console()
        if latex_file is None:
            self.latex_file = os.path.join(os.getcwd(), self.DEFAULT_FILENAME)
        else:
            self.latex_file = latex_file
        if not os.path.exists(self.latex_file):
            self.create_initial_tex_file()
        self.max_word_length = 50
        self.word_entries: Dict[str, Dict] = {}
        self.normalized_entries: Dict[str, str] = {}
        self.config_file = "vocab_builder_config.json"
        self.client = None
        self.client_lock = threading.Lock()
        self.client_initialized = threading.Event()
        
        self.load_config()
        if 'ANTHROPIC_API_KEY' not in os.environ:
            self.console.print("[bold red]ANTHROPIC_API_KEY not set in environment variables after loading config.[/bold red]")
        # Start the Anthropic client initialization in a separate thread
        threading.Thread(target=self.initialize_anthropic_client_background, daemon=True).start()
        
        load_config_start = time.time()
        self.load_config()
        load_config_end = time.time()
        
        load_entries_start = time.time()
        self.load_existing_entries()
        load_entries_end = time.time()
        
        self.exported_words_file = "exported_words.json"
        self.exported_words = self.load_exported_words()
        self.entry_count = self.count_entries()

        init_end = time.time()
        print(f"Total init time: {init_end - init_start:.5f} seconds")
        print(f"  Load config time: {load_config_end - load_config_start:.5f} seconds")
        print(f"  Load entries time: {load_entries_end - load_entries_start:.5f} seconds")

    def create_initial_tex_file(self):
        try:
            os.makedirs(os.path.dirname(self.latex_file), exist_ok=True)
            with open(self.latex_file, 'w', encoding='utf-8') as file:
                file.write(INITIAL_TEX_CONTENT)
                file.write(SAMPLE_ENTRY)
                file.write(FINAL_TEX_CONTENT)
            self.console.print(f"[bold green]Created initial LaTeX file: {self.latex_file}[/bold green]")
        except IOError as e:
            self.console.print(f"[bold red]Error creating initial LaTeX file: {e}[/bold red]")
            raise

    def load_config(self):
        if not os.path.exists(self.config_file):
            self.first_time_setup()
        else:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                os.environ['ANTHROPIC_API_KEY'] = config['ANTHROPIC_API_KEY']

    def initialize_anthropic_client_background(self):
        try:
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if api_key:
                self.client = anthropic.Anthropic(api_key=api_key)
                # Test the client with a simple request
                self.client.messages.create(
                    model="claude-3-5-sonnet-20240620",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Hello"}]
                )
                self.console.print("[bold green]Anthropic client initialized successfully![/bold green]")
            else:
                self.console.print("[bold red]ANTHROPIC_API_KEY not found in environment variables.[/bold red]")
                self.console.print(f"Config file path: {self.config_file}")
                if os.path.exists(self.config_file):
                    with open(self.config_file, 'r') as f:
                        self.console.print(f"Config file contents: {f.read()}")
                else:
                    self.console.print("Config file does not exist.")
        except Exception as e:
            self.console.print(f"[bold red]Error initializing Anthropic client: {e}[/bold red]")
        finally:
            self.client_initialized.set()

    def get_anthropic_client(self):
        if not self.client_initialized.is_set():
            self.console.print("Waiting for Anthropic client to initialize...")
            self.client_initialized.wait()
        return self.client

    def first_time_setup(self):
        self.console.print("[bold blue]Welcome to French Vocabulary Builder![/bold blue]")
        self.console.print("It looks like this is your first time running the program or the API key is not set.")
        api_key = Prompt.ask("Please enter your Anthropic API key")

        config = {'ANTHROPIC_API_KEY': api_key}
        with open(self.config_file, 'w') as f:
            json.dump(config, f)

        os.environ['ANTHROPIC_API_KEY'] = api_key
        self.console.print(f"[bold green]API key saved successfully:{api_key}![/bold green]")

    def load_exported_words(self):
        if os.path.exists(self.exported_words_file):
            with open(self.exported_words_file, 'r') as f:
                return set(json.load(f))
        return set()

    def save_exported_words(self):
        with open(self.exported_words_file, 'w') as f:
            json.dump(list(self.exported_words), f)

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
            r"\\entry\{(.*?)\}\{(.*?)\}\s*\{(.*?)\}\s*\{(.*?)\}", content, re.DOTALL
        )
        for word, word_type, definitions, examples in entries:
            word = word.strip().lower()  # Normalize the word
            self.word_entries[word] = {
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

    def latex_to_anki_format(self, text):
        # Remove LaTeX item markers and ensure each item starts on a new line
        text = re.sub(r'\\item\s*', '\n• ', text)

        # Convert LaTeX newlines to HTML line breaks
        text = text.replace('\\\\ ', '<br>')

        # Remove any remaining LaTeX commands
        text = re.sub(r'\\[a-zA-Z]+(\[.*?\])?(\{.*?\})?', '', text)

        # Ensure the text starts with a bullet point
        if not text.startswith('• '):
            text = '• ' + text

        # Remove any extra newlines
        text = re.sub(r'\n+', '\n', text)

        # Trim whitespace
        text = text.strip()

        return text

    def normalize_word(self, word: str) -> str:
        word = word.lower().strip()
        return ''.join(c for c in unicodedata.normalize('NFD', word) if unicodedata.category(c) != 'Mn')

    def export_to_anki(self, deck_name: str = "French Vocabulary"):
        model_id = random.randrange(1 << 30, 1 << 31)
        model = genanki.Model(
            model_id,
            'French Vocab Model',
            fields=[
                {'name': 'French'},
                {'name': 'Type'},
                {'name': 'English'},
                {'name': 'Example'},
            ],
            templates=[
                {
                    'name': 'Card 1',
                    'qfmt': '{{French}}<br>{{Type}}',
                    'afmt': '{{FrontSide}}<hr id="answer">{{English}}<br><br>Example:<br>{{Example}}',
                },
            ])

        deck_id = random.randrange(1 << 30, 1 << 31)
        deck = genanki.Deck(deck_id, deck_name)

        newly_added_words = set()

        for word, entry in self.word_entries.items():
            word = word.strip().lower()

            if word not in self.exported_words:
                # Convert word_type to string if it's a list
                word_type = entry['type'] if isinstance(entry['type'], str) else ', '.join(entry['type'])

                note = genanki.Note(
                    model=model,
                    fields=[
                        entry['word'],
                        word_type,  # Use the potentially converted word_type
                        self.latex_to_anki_format(entry['definitions']),
                        self.latex_to_anki_format(entry['examples'])
                    ])
                deck.add_note(note)
                self.exported_words.add(word)
                newly_added_words.add(word)

        genanki.Package(deck).write_to_file(f'{deck_name}.apkg')
        self.save_exported_words()

        # Prepare the feedback message
        feedback = f"""
        [bold green]Anki deck '{deck_name}.apkg' created successfully![/bold green]

        [bold blue]Total words in deck: {len(self.exported_words)}[/bold blue]
        [bold cyan]Newly added words in this export: {len(newly_added_words)}[/bold cyan]

        New words added:
        {', '.join(sorted(newly_added_words)) if newly_added_words else 'No new words added in this export.'}
        """

        # Display the feedback in a panel
        self.console.print(Panel(feedback, title="Export Summary", expand=False, border_style="green"))

    def check_duplicate(self, word: str) -> Optional[str]:
        normalized_word = self.normalize_word(word)
        return self.normalized_entries.get(normalized_word)

    def handle_duplicate(self, word: str, existing_word: str) -> bool:
        self.console.print(
            f"[bold yellow]Warning: '{word}' already exists in the dictionary as '{existing_word}'.[/bold yellow]")
        self.console.print("\nPlease choose an action:")
        self.console.print("[s] Skip: Don't add this word and return to the main menu.")
        self.console.print("[v] View: Display the existing entry for this word.")
        self.console.print("[f] Force Add: Add this word as a new entry despite the duplication.")

        choice = Prompt.ask("Your choice", choices=["s", "v", "f"], default="s")

        if choice == "s":
            self.console.print("Skipping this word. Returning to main menu.")
            return False
        elif choice == "v":
            self.console.print(f"\nDisplaying existing entry for '{existing_word}':")
            self.display_existing_entry(existing_word)
            self.console.print("\nReturning to main menu without adding a new entry.")
            return False
        else:  # choice == "f"
            self.console.print(f"Proceeding to add '{word}' as a new entry, even though it may be a duplicate.")
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
        console.print("2. Export to Anki deck")
        console.print("3. Exit")
        console.print(f"[bold green]Current word count: {self.entry_count}[/bold green]")
        choice = Prompt.ask("Choose an option", choices=["1", "2", "3"])
        return choice

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

            if len(word.split()) > 10:
                console.print(
                    "[bold red]Error: Please enter a single word or short expression (max 10 words).[/bold red]"
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
        client = self.get_anthropic_client()
        if not client:
            return "[bold red]Failed to initialize Anthropic client. Please check your API key and try again.[/bold red]"
        
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
            word_type: str = "Unknown"

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
            examples: List[Tuple[str, str]]
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
            self.entry_count = self.count_entries()
            choice = self.show_menu()
            if choice == "1":
                word = self.get_and_validate_word()
                if word:
                    ai_response = self.query_ai(word)
                    if ai_response:
                        self.process_ai_response(word, ai_response)
                        self.add_word_to_entries(word, ai_response)
                        self.alphabetize_entries()
                    else:
                        self.console.print(f"[bold red]Failed to get information for '{word}'. Skipping this entry.[/bold red]")
            elif choice == "2":
                self.handle_anki_export()
            elif choice == "3":
                self.exit_screen()
                break
            self.console.input("\nPress Enter to continue...")

    def handle_new_word_entry(self):
        """
        Handles the process of adding a new word entry to the vocabulary.

        This method performs the following steps:
        1. Gets and validates a new word input from the user.
        2. Queries the AI for information about the word.
        3. Processes the AI response and adds the word to the entries.
        4. Alphabetizes the entries after adding the new word.

        If at any point the process fails (e.g., invalid word, AI query fails),
        the method will return early without adding the word.

        Returns:
            None
        """
        word = self.get_and_validate_word()
        if not word:
            return
        
        ai_response = self.query_ai(word)
        if not ai_response:
            self.console.print(f"[bold red]Failed to get information for '{word}'. Skipping this entry.[/bold red]")
            return

        word = self.process_ai_response(word, ai_response)
        self.add_word_to_entries(word)
        self.alphabetize_entries()

    def get_and_validate_word(self):
        word = self.get_word_input()
        existing_word = self.check_duplicate(word)
        if existing_word and not self.handle_duplicate(word, existing_word):
            return None
        return word

    def process_ai_response(self, word, ai_response):
        word_type, definitions, examples = self.parse_ai_response(ai_response)
        self.display_parsed_info(word, word_type, definitions, examples)

        word = self.check_spelling(word, ai_response)

        latex_entry = self.format_latex_entry(word, word_type, definitions, examples)
        self.display_latex_entry(latex_entry)
        self.insert_entry_alphabetically(latex_entry, word.capitalize())
        self.add_word_to_entries(word, ai_response)

        return word

    def check_spelling(self, word, ai_response):
        corrected_spelling_match = re.search(r'Correctly Spelt Word:\s*(.*)', ai_response)
        corrected_spelling = corrected_spelling_match.group(1) if corrected_spelling_match else None
        
        if corrected_spelling and corrected_spelling.lower() != word.lower():
            if Confirm.ask(f"Did you mean '{corrected_spelling}' instead of '{word}'?"):
                return corrected_spelling
        return word

    def add_word_to_entries(self, word, ai_response):
        word_type, definitions, examples = self.parse_ai_response(ai_response)
        self.word_entries[word.lower()] = {
            "word": word.capitalize(),
            "type": word_type,
            "definitions": "; ".join(definitions),
            "examples": "; ".join([f"{f} ({e})" for f, e in examples]),
        }

    def handle_anki_export(self):
        deck_name = Prompt.ask("Enter a name for your Anki deck", default="French Vocabulary")
        self.export_to_anki(deck_name)
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
    start_time = time.time()
    
    if len(sys.argv) > 1:
        latex_file = sys.argv[1]
    else:
        latex_file = None

    init_start = time.time()
    app = FrenchVocabBuilder("/Users/sihao/Documents/LaTeX Files/FrenchVocab.tex")
    init_end = time.time()
    
    run_start = time.time()
    app.run()
    run_end = time.time()

    print(f"Total startup time: {init_end - start_time:.2f} seconds")
    print(f"Initialization time: {init_end - init_start:.2f} seconds")
    print(f"Run time: {run_end - run_start:.2f} seconds")

if __name__ == "__main__":
    main()
