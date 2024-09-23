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
from rich.progress import Progress
from rich.prompt import Prompt, Confirm
from enum import Enum, auto
from latex_templates import INITIAL_TEX_CONTENT, SAMPLE_ENTRY, FINAL_TEX_CONTENT, AI_PROMPT_TEMPLATE
import time
import threading
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

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
        self.max_word_length = 100
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
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            self.first_time_setup()
        else:
            self.console.print("[bold green]ANTHROPIC_API_KEY found in environment variables.[/bold green]")

    def initialize_anthropic_client_background(self):
        try:
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if api_key and api_key.startswith("sk-ant") and len(api_key) >= 32:
                self.client = anthropic.Anthropic(api_key=api_key)
                self.console.print("[bold green]Anthropic client initialized successfully![/bold green]")
            else:
                self.console.print("[bold red]Invalid or missing ANTHROPIC_API_KEY in environment variables.[/bold red]")
                self.provide_api_key_instructions()
        except Exception as e:
            self.console.print(f"[bold red]Error initializing Anthropic client: {e}[/bold red]")
            self.provide_api_key_instructions()
        finally:
            self.client_initialized.set()

    def provide_api_key_instructions(self):
        instructions = """
        [bold yellow]To obtain an Anthropic API key:[/bold yellow]
        1. Go to https://www.anthropic.com or https://console.anthropic.com
        2. Sign up for an account or log in if you already have one
        3. Navigate to the API section in your account dashboard
        4. Generate a new API key
        5. Copy the key and set it as an environment variable:
           [bold cyan]export ANTHROPIC_API_KEY='your-api-key-here'[/bold cyan]
        6. Restart the application
        
        [bold]Note:[/bold] Keep your API key secure and never share it publicly.
        """
        self.console.print(Panel(instructions, title="Anthropic API Key Instructions", expand=False))

    def get_anthropic_client(self):
        if not self.client_initialized.is_set():
            self.console.print("Waiting for Anthropic client to initialize...")
            self.client_initialized.wait()
        return self.client

    def first_time_setup(self):
        self.console.print("[bold blue]Welcome to French Vocabulary Builder![/bold blue]")
        self.console.print("It looks like this is your first time running the program or the API key is not set.")
        self.console.print("Please set your Anthropic API key as an environment variable named ANTHROPIC_API_KEY.")
        self.console.print("You can do this by running:")
        self.console.print("export ANTHROPIC_API_KEY='your-api-key-here'")
        sys.exit(1)

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
        """Converts LaTeX-formatted text to Anki-compatible HTML format.

        This method processes a given LaTeX string by removing LaTeX-specific
        commands, converting newlines to HTML line breaks, and formatting
        list items with bullet points suitable for Anki flashcards.

        Args:
            text (str): The LaTeX-formatted string to be converted.

        Returns:
            str: The converted string formatted with HTML line breaks and
                 bullet points, ready for Anki import.
        """
        # Remove LaTeX item markers
        text = re.sub(r'\\item\s*', '', text)
        
        # Convert LaTeX newlines to HTML line breaks
        text = text.replace('\\\\ ', '<br>')
        
        # Remove any remaining LaTeX commands
        text = re.sub(r'\\[a-zA-Z]+(\[.*?\])?(\{.*?\})?', '', text)
        
        # Split the text into individual items
        items = [item.strip() for item in text.split('\n') if item.strip()]
        
        # Add bullet points to each item
        formatted_items = [f'• {item}' for item in items]
        
        # Join the items with HTML line breaks
        formatted_text = '<br>'.join(formatted_items)
        
        return formatted_text.strip()

    def normalize_word(self, word: str) -> str:
        """Normalize a given word by converting it to lowercase and removing accents.

        This method takes a word, converts it to lowercase, strips any leading and trailing 
        whitespace, and removes diacritical marks (accents) to produce a normalized version 
        of the word.

        Args:
            word (str): The word to normalize.

        Returns:
            str: The normalized word without accents.
        """
        word = word.lower().strip()
        return ''.join(c for c in unicodedata.normalize('NFD', word) if unicodedata.category(c) != 'Mn')

    def export_to_anki(self, deck_name: str = "French Vocabulary"):
        """Exports the French vocabulary entries to an Anki deck.

        This method creates an Anki deck using the genanki library by iterating over
        the current vocabulary entries, formatting each entry into an Anki note, and
        adding it to the deck. Only words that have not been exported before are
        included to avoid duplicates.

        Args:
            deck_name (str, optional): The name of the Anki deck to be created.
                Defaults to "French Vocabulary".

        Raises:
            IOError: If there's an error writing the Anki package file.
        """
        model_id = random.randrange(1 << 30, 1 << 31)
        # Define the model for Anki notes
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

        # Generate a unique deck ID
        deck_id = random.randrange(1 << 30, 1 << 31)
        # Create a new Anki deck with the specified name and ID
        deck = genanki.Deck(deck_id, deck_name)

        # Set to keep track of newly added words in this export
        newly_added_words = set()

        # Iterate over all word entries
        for word, entry in self.word_entries.items():
            # Normalize the word by stripping whitespace and converting to lowercase
            word = word.strip().lower()

            # Check if the word has already been exported to Anki
            if word not in self.exported_words:
                # Ensure word_type is always a string
                word_type = ', '.join(entry['type']) if isinstance(entry['type'], list) else entry['type']

                # Create a new Anki note with the formatted fields
                note = genanki.Note(
                    model=model,
                    fields=[
                        entry['word'],
                        word_type,
                        self.latex_to_anki_format(entry['definitions']),
                        self.latex_to_anki_format(entry['examples']),
                    ])
                # Add the note to the deck
                deck.add_note(note)
                # Mark the word as exported
                self.exported_words.add(word)
                # Add the word to the set of newly added words
                newly_added_words.add(word)

        # Write the deck to a .apkg file
        genanki.Package(deck).write_to_file(f'{deck_name}.apkg')
        # Save the state of exported words to persist across sessions
        self.save_exported_words()

        # Prepare the feedback message for the user
        feedback = f"""
        [bold green]Anki deck '{deck_name}.apkg' created successfully![/bold green]

        [bold blue]Total words in deck: {len(self.exported_words)}[/bold blue]
        [bold cyan]Newly added words in this export: {len(newly_added_words)}[/bold cyan]

        New words added:
        {', '.join(sorted(newly_added_words)) if newly_added_words else 'No new words added in this export.'}
        """

        # Display the feedback in a styled panel using Rich
        self.console.print(Panel(feedback, title="Export Summary", expand=False, border_style="green"))

    def check_duplicate(self, word: str) -> Optional[str]:
        normalized_word = self.normalize_word(word)
        return self.normalized_entries.get(normalized_word)

    def handle_duplicate(self, word: str, existing_word: str) -> bool:
        warning_text = Text(f"Warning: '{word}' already exists in the dictionary as '{existing_word}'.", style="bold yellow")
        self.console.print(Panel(warning_text, border_style="yellow"))

        # Create a table for options
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(style="cyan", no_wrap=True)
        table.add_column(style="white")
        table.add_row("[s]", "Skip: Don't add this word and return to the main menu.")
        table.add_row("[v]", "View: Display the existing entry for this word.")
        table.add_row("[f]", "Force Add: Add this word as a new entry despite the duplication.")

        self.console.print(Panel(table, title="Please choose an action", border_style="blue"))

        choice = Prompt.ask("Your choice", choices=["s", "v", "f"], default="s")

        if choice == "s":
            self.console.print(Panel("Skipping this word. Returning to main menu.", border_style="green"))
            return False
        elif choice == "v":
            self.console.print(Panel(f"Displaying existing entry for '{existing_word}':", border_style="cyan"))
            self.display_existing_entry(existing_word)
            self.console.print(Panel("Returning to main menu without adding a new entry.", border_style="green"))
            return False
        else:  # choice == "f"
            self.console.print(Panel(f"Proceeding to add '{word}' as a new entry, even though it may be a duplicate.", border_style="magenta"))
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
            word = input("\nEnter a French word or short expression (or 'q' to cancel): ").strip()
            
            if word.lower() == 'q':
                self.console.print("[yellow]Input cancelled. Returning to main menu.[/yellow]")
                return ""
            
            if len(word.split()) > 10:
                self.console.print("[bold red]Error: Please enter a single word or short expression (max 10 words).[/bold red]")
            elif len(word) > self.max_word_length:
                self.console.print(f"[bold red]Error: Input is too long. Please limit to {self.max_word_length} characters.[/bold red]")
            elif not word:
                self.console.print("[bold red]Error: Input cannot be empty.[/bold red]")
            elif not self.is_valid_french_input(word):
                self.console.print("[bold red]Error: Input contains invalid characters for French words.[/bold red]")
            else:
                return word

    def is_valid_french_input(self, word: str) -> bool:
        # Allow letters (including accented), spaces, hyphens, and apostrophes
        return all(char.isalpha() or char.isspace() or char in "'-àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ" for char in word.strip())

    def query_ai(self, word: str) -> str:
        client = self.get_anthropic_client()
        if not client:
            return "[bold red]Failed to initialize Anthropic client. Please check your API key and try again.[/bold red]"
        
        prompt = AI_PROMPT_TEMPLATE.format(word=word)
        with Progress() as progress:
            task = progress.add_task("[cyan]Querying AI...", total=100)

            try:
                message = client.messages.create(
                    model="claude-3-5-sonnet-20240620",
                    max_tokens=8192,
                    temperature=0.1,
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
            normalized_new_word = self.normalize_word(new_word)
            self.normalized_entries[normalized_new_word] = new_word.capitalize()

        except FileNotFoundError:
            console.print(f"[bold red]Error: File not found - {self.latex_file}[/bold red]")
        except IOError as e:
            console.print(f"[bold red]Error reading from or writing to file: {e}[/bold red]")

    def alphabetize_entries(self) -> None:
        """Alphabetizes the entries in the LaTeX file.

        This method reads the LaTeX file, identifies the section containing 
        vocabulary entries, and sorts them alphabetically based on the 
        normalized form of the words. The sorted entries are then written 
        back to the LaTeX file.

        Raises:
            FileNotFoundError: If the LaTeX file does not exist.
            IOError: If there is an error reading from or writing to the file.
        """
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

            # Sort entries based on the normalized word (first argument of \entry)
            sorted_entries = sorted(
                entries,
                key=lambda x: self.normalize_word(re.search(r"\\entry\{(.*?)\}", x).group(1))
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
                self.handle_new_word_entry()
            elif choice == "2":
                self.handle_anki_export()
            elif choice == "3":
                self.exit_screen()
                break
            self.console.input("\nPress Enter to continue...")

    def handle_new_word_entry(self):
        word = self.get_word_input()
        if word:
            existing_word = self.check_duplicate(word)
            if existing_word:
                if not self.handle_duplicate(word, existing_word):
                    return  # User chose to skip or view existing entry
            
            ai_response = self.query_ai(word)
            if ai_response:
                word = self.check_spelling(word, ai_response)
                if word is None:  # User chose to abandon the edit
                    return
                self.process_ai_response(word, ai_response)
                self.add_word_to_entries(word, ai_response)
                self.alphabetize_entries()
            else:
                self.console.print(f"[bold red]Failed to get information for '{word}'. Skipping this entry.[/bold red]")

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

        spelling_check_match = re.search(r'Spelling Check:\s*(.*)', ai_response)
        spelling_check = spelling_check_match.group(1) if spelling_check_match else None

        corrected_spelling_match = re.search(r'Correctly Spelt Word:\s*(.*)', ai_response)
        corrected_spelling = corrected_spelling_match.group(1) if corrected_spelling_match else None


        if corrected_spelling and corrected_spelling.lower().strip() != word.lower().strip():
            self.console.print(f"Did you mean '{corrected_spelling}' instead of '{word}'?")
            self.console.print("y: Yes, use the corrected spelling")
            self.console.print("n: No, keep the original spelling")
            self.console.print("q: Quit and abandon this edit")
            choice = Prompt.ask("Your choice", choices=["y", "n", "q"], default="y")
            
            if choice == "y":
                return corrected_spelling
            elif choice == "q":
                self.console.print("[yellow]Abandoning edit. Returning to main menu.[/yellow]")
                return None
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