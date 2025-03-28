import json
import os
import random
import re
import unicodedata
from typing import List, Tuple, Optional, Dict, Set
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
import keyring
import getpass
from keyring.errors import KeyringError
from pathlib import Path

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
    def __init__(self, latex_file: Optional[str]):
        init_start = time.time()
        
        self.console = Console()
        # Use pathlib for cross-platform file handling
        if latex_file is None:
            self.latex_file = Path.cwd() / self.DEFAULT_FILENAME
        else:
            self.latex_file = Path(latex_file)
        if not self.latex_file.exists():
            self.create_initial_tex_file()
        
        self.max_word_length = 500
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
        
        self.exported_words_file = Path("exported_words.json")
        self.exported_words = self.load_exported_words()
        self.entry_count = self.count_entries()

        init_end = time.time()
        print(f"Total init time: {init_end - init_start:.5f} seconds")
        print(f"  Load config time: {load_config_end - load_config_start:.5f} seconds")
        print(f"  Load entries time: {load_entries_end - load_entries_start:.5f} seconds")

    def create_initial_tex_file(self):
        try:
            # Create the parent directory if needed (only if not in the current directory)
            if self.latex_file.parent != Path('.'):
                self.latex_file.parent.mkdir(parents=True, exist_ok=True)
            with self.latex_file.open('w', encoding='utf-8') as file:
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
            try:
                api_key = keyring.get_password("french_vocab_builder", "anthropic_api_key")
            except KeyringError as e:
                self.console.print(f"[bold red]Error accessing keyring: {e}[/bold red]")
                api_key = None
        
        if not api_key or not self.is_valid_api_key(api_key):
            api_key = self.first_time_setup()
        
        os.environ['ANTHROPIC_API_KEY'] = api_key
        self.console.print("[bold green]Valid ANTHROPIC_API_KEY found and set.[/bold green]")

    def is_valid_api_key(self, api_key):
        # Basic check
        if not api_key or not api_key.startswith("sk-ant") or len(api_key) < 32:
            return False
        
        # Optional: Perform a test API call here to verify the key works
        # Return True if the call succeeds, False otherwise
        return True

    def first_time_setup(self):
        self.console.print(Panel(
            "[bold yellow]No valid ANTHROPIC_API_KEY found. Let's set it up.[/bold yellow]\n\n"
            "To obtain an API key:\n"
            "1. Go to https://www.anthropic.com or https://console.anthropic.com\n"
            "2. Sign up or log in to your account\n"
            "3. Navigate to the API section in your account dashboard\n"
            "4. Generate a new API key\n"
            "The key should start with 'sk-ant' and be at least 32 characters long.",
            title="API Key Setup",
            expand=False
        ))
        
        while True:
            api_key = getpass.getpass("Enter your Anthropic API key: ")
            if self.is_valid_api_key(api_key):
                try:
                    keyring.set_password("french_vocab_builder", "anthropic_api_key", api_key)
                    self.console.print("[bold green]API key saved securely.[/bold green]")
                    return api_key
                except KeyringError as e:
                    self.console.print(f"[bold red]Error saving to keyring: {e}[/bold red]")
                    if Confirm.ask("Do you want to continue without saving to keyring?"):
                        return api_key
            else:
                self.console.print("[bold red]Invalid API key. Please try again.[/bold red]")
        

    def initialize_anthropic_client_background(self):
        try:
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if api_key and api_key.startswith("sk-ant") and len(api_key) >= 32:
                self.client = anthropic.Anthropic(api_key=api_key)
                self.console.print("[bold green]Anthropic client initialized successfully![/bold green]")
            else:
                self.console.print("[bold red]Invalid or missing ANTHROPIC_API_KEY in environment variables.[/bold red]")
                self.provide_api_key_instructions()
                sys.exit(1)
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
        5. Copy the key and set it as an environment variable by typing the following command in your console:
           [bold cyan]For MacOS:[/bold cyan]
           export ANTHROPIC_API_KEY='your-api-key-here'
           [bold cyan]For Windows (Command Prompt):[/bold cyan]
           set ANTHROPIC_API_KEY='your-api-key-here'
           [bold cyan]For Windows (PowerShell):[/bold cyan]
           $env:ANTHROPIC_API_KEY='your-api-key-here'
        6. After setting the environment variable, restart the application.
        
        The program will now abort due to the need of an API key.
        [bold]Note:[/bold] Keep your API key secure and never share it publicly.
        """
        self.console.print(Panel(instructions, title="Anthropic API Key Instructions", expand=False))

    def get_anthropic_client(self):
        if not self.client_initialized.is_set():
            self.console.print("Waiting for Anthropic client to initialize...")
            self.client_initialized.wait()
        return self.client

    def load_exported_words(self):
        if self.exported_words_file.exists():
            with self.exported_words_file.open('r') as f:
                return set(json.load(f))
        return set()
    def save_exported_words(self):
        with self.exported_words_file.open('w') as f:
            json.dump(list(self.exported_words), f)

    def count_entries(self) -> int:
        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()
            return len(re.findall(r"\\entry\{", content))
        except FileNotFoundError:
            console.print(f"[bold red]Error: File not found - {self.latex_file}[/bold red]")
            return 0
        except IOError as e:
            console.print(f"[bold red]Error reading file: {e}[/bold red]")
            return 0
            console.print(f"[bold red]Error: File not found - {self.latex_file}[/bold red]")
            return 0
        except IOError as e:
            console.print(f"[bold red]Error reading file: {e}[/bold red]")
            return 0


    def load_existing_entries(self):
        """Loads existing vocabulary entries from the LaTeX file."""
        try: # Add try...finally to ensure file is closed
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()
        except FileNotFoundError:
            self.console.print(f"[bold red]Error: File not found - {self.latex_file}[/bold red]")
            return
        except IOError as e:
            self.console.print(f"[bold red]Error reading file: {e}[/bold red]")
            return

        # Find ALL potential entry starts
        raw_entry_starts = [match.start() for match in re.finditer(r"\\entry\{", content)]
        raw_entry_count_debug = len(raw_entry_starts)

        # Use the stricter regex to find successfully parsed entries
        parsed_entries = re.findall(
            r"\\entry\{(.*?)\}\{(.*?)\}\s*\{(.*?)\}\s*\{(.*?)\}", content, re.DOTALL
        )

        # Keep track of successfully parsed words (lowercase, normalized)
        parsed_words_set = set()

        self.word_entries.clear() # Clear existing entries before loading
        self.normalized_entries.clear()
        key_collisions = {} # Dictionary to track collisions: {key: [list_of_original_words_producing_this_key]}

        skipped_entry_details = [] # Store details of skipped entries

        for i, (word, word_type, definitions, examples) in enumerate(parsed_entries):
            original_word_for_log = word.strip() # Keep original case for logging
            word_lower = word.strip().lower()  # Normalize the word

            # Check for empty content (the original check)
            if not word_lower or not word_type or not definitions.strip() or not examples.strip():
                reason = []
                if not word_lower: reason.append("empty word")
                if not word_type: reason.append("empty type")
                if not definitions.strip(): reason.append("empty definitions")
                if not examples.strip(): reason.append("empty examples")
                # Store info about skipped entry due to content validation
                skipped_entry_details.append({
                    "word": original_word_for_log or '[EMPTY WORD]',
                    "reason": f"Content Validation Failed: {', '.join(reason)}",
                    "index_in_parsed": i
                })
                self.console.print(f"[bold yellow]Skipping entry due to content: '{original_word_for_log or '[EMPTY WORD]'}' - Reason: {', '.join(reason)}[/bold yellow]")
                continue

            # --- Check for key collision BEFORE assigning ---
            if word_lower in self.word_entries:
                # Collision detected for self.word_entries!
                if word_lower not in key_collisions:
                    key_collisions[word_lower] = [self.word_entries[word_lower]['word']] # Add the word already there
                key_collisions[word_lower].append(original_word_for_log) # Add the new word causing collision

                self.console.print(f"[bold orange3]WARNING: Key collision detected for key '{word_lower}'. Overwriting entry for '{self.word_entries[word_lower]['word']}' with entry for '{original_word_for_log}'.[/bold orange3]")

            # Add to successful entries
            self.word_entries[word_lower] = {
                "word": original_word_for_log.capitalize(), # Store capitalized original
                "type": word_type.strip(),
                "definitions": definitions.strip(),
                "examples": examples.strip(),
            }

            # Also check collision for normalized_entries (less likely to be the primary issue based on counts, but good practice)
            normalized_word = self.normalize_word(word_lower)
            if normalized_word in self.normalized_entries and self.normalized_entries[normalized_word] != word_lower:
                 self.console.print(f"[bold yellow]NOTE: Normalized key collision for '{normalized_word}'. Mapping from '{self.normalized_entries[normalized_word]}' overwritten by '{word_lower}'.[/bold yellow]")
            self.normalized_entries[normalized_word] = word_lower

            parsed_words_set.add(original_word_for_log.strip()) # Add original word as parsed

        loaded_entries_count_debug = len(self.word_entries)

        # --- Find entries missed by the REGEX ---
        missed_by_regex = []
        # Extract the word part from ALL raw \entry{ lines for comparison
        all_raw_words = re.findall(r"\\entry\{(.*?)\}", content, re.DOTALL)
        all_raw_words_stripped = {w.strip() for w in all_raw_words}

        missed_words = all_raw_words_stripped - parsed_words_set

        if missed_words:
             self.console.print(f"[bold red]DEBUG: Found {len(missed_words)} words present in raw \\entry{{...}} but NOT successfully parsed by the 4-group regex:[/bold red]")
             # Try to find the context of these missed words in the original file
             for word in sorted(list(missed_words)):
                 # Find the line number (approximate)
                 try:
                     escaped_word = re.escape(word)
                     match = re.search(fr"\\entry{{{escaped_word}}}", content)
                     if match:
                         start_index = match.start()
                         line_number = content.count('\n', 0, start_index) + 1
                         # Extract a snippet around the match
                         context_start = max(0, start_index - 30)
                         context_end = min(len(content), start_index + 150) # Look further ahead
                         snippet = content[context_start:context_end].replace('\n', '\\n')
                         missed_by_regex.append(f"Word: '{word}' (approx line {line_number}) - Snippet: ...{snippet}...")
                     else:
                         missed_by_regex.append(f"Word: '{word}' (Could not find exact context)")
                 except Exception as e:
                      missed_by_regex.append(f"Word: '{word}' (Error finding context: {e})")

        # --- Final Debug Summary ---
        self.console.print(f"[bold magenta]DEBUG: Initial raw \\entry{{ count: {raw_entry_count_debug}[/bold magenta]")
        self.console.print(f"[bold magenta]DEBUG: Entries matched by 4-group regex: {len(parsed_entries)}[/bold magenta]")
        self.console.print(f"[bold magenta]DEBUG: Entries skipped by content validation: {len(skipped_entry_details)}[/bold magenta]")
        self.console.print(f"[bold magenta]DEBUG: Final loaded entries (self.word_entries): {loaded_entries_count_debug}[/bold magenta]")

        # --- Permanent Warning for Duplicates (Always Show) ---
        if key_collisions:
            self.console.print(Panel(
                f"[bold yellow]WARNING:[/bold yellow] {len(key_collisions)} duplicate word key(s) detected during loading, resulting in {sum(len(v)-1 for v in key_collisions.values())} overwritten entries.\n"
                "The application uses the *last* encountered entry for each duplicate word.\n"
                "Please review your `.tex` file and remove redundant entries for:\n" +
                "\n".join([f" - Key: '{key}' (from words: {', '.join(words)})" for key, words in key_collisions.items()]),
                title="Duplicate Entries Found",
                border_style="yellow"
            ))

        # Update the main count AFTER all checks
        self.entry_count = len(self.word_entries)

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

        # Create sets for all words in LaTeX and all words ever exported to Anki
        latex_words = set(self.word_entries.keys())
        all_exported_words = set(self.exported_words)  # This should contain all previously exported words

        # Set to keep track of newly added words in this export
        newly_added_words = set()

        # Iterate over all word entries
        for word, entry in self.word_entries.items():
            # Normalize the word by stripping whitespace and converting to lowercase
            word = word.strip().lower()

            # Check if the word has already been exported to Anki
            if word not in all_exported_words:
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
                all_exported_words.add(word)
                # Add the word to the set of newly added words
                newly_added_words.add(word)

        # Write the deck to a .apkg file
        genanki.Package(deck).write_to_file(f'{deck_name}.apkg')

        # Update the exported_words set and save it
        self.exported_words = all_exported_words
        self.save_exported_words()

        # Prepare the feedback message for the user
        feedback = f"""
        [bold green]Anki deck '{deck_name}.apkg' created successfully![/bold green]

        [bold blue]Total words in deck: {len(all_exported_words)}[/bold blue]
        [bold cyan]Newly added words in this export: {len(newly_added_words)}[/bold cyan]

        New words added:
        {', '.join(sorted(newly_added_words)) if newly_added_words else 'No new words added in this export.'}
        """

        # Compare LaTeX words with all exported words
        missing_from_anki = latex_words - all_exported_words
        extra_in_anki = all_exported_words - latex_words

        feedback += f"\n\nWords in LaTeX but not in Anki: {len(missing_from_anki)}"
        if missing_from_anki:
            feedback += f"\n{', '.join(sorted(missing_from_anki))}"
        
        feedback += f"\n\nWords in Anki but not in LaTeX: {len(extra_in_anki)}"
        if extra_in_anki:
            feedback += f"\n{', '.join(sorted(extra_in_anki))}"

        # Display the feedback in a styled panel using Rich
        self.console.print(Panel(feedback, title="Export Summary", expand=False, border_style="green"))

    def check_duplicate(self, word: str) -> Optional[str]:
        normalized_word = self.normalize_word(word)
        return self.normalized_entries.get(normalized_word)

    def handle_duplicate(self, word: str, existing_word: str) -> bool:
        # Use the actual key from normalized_entries for consistency
        normalized_word = self.normalize_word(word)
        actual_existing_word = self.normalized_entries.get(normalized_word, existing_word) # Get the stored version

        warning_text = Text(f"Duplicate Warning:\nWord '{word}' (normalized: '{normalized_word}') already exists in the dictionary as '{actual_existing_word}'.", style="bold yellow")
        # Use a red border for higher visibility
        self.console.print(Panel(warning_text, border_style="bold red", title="Duplicate Found!"))

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
            self.console.print(Panel(f"Displaying existing entry for '{actual_existing_word}':", border_style="cyan"))
            # Ensure you use the correct key to retrieve the entry
            self.display_existing_entry(actual_existing_word.lower()) # Use the lowercase version which should be the key
            # Ask again after viewing
            self.console.print(Panel("Returning to duplicate handling options...", border_style="blue"))
            # Recursive call to handle_duplicate to ask again after viewing
            return self.handle_duplicate(word, existing_word)
        else:  # choice == "f"
            if Confirm.ask(f"[bold red]Are you absolutely sure you want to add '{word}'? This will create a duplicate entry based on the normalized word '{normalized_word}'. Existing entry is '{actual_existing_word}'.", default=False):
                self.console.print(Panel(f"Proceeding to add '{word}' as a new entry, despite the duplication.", border_style="magenta"))
                return True
            else:
                self.console.print(Panel("Force Add cancelled. Skipping this word.", border_style="yellow"))
                return False

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
                f"[bold green]Your current vocabulary library contains {self.entry_count} words.[/bold green]\n\n"
                f"[italic cyan]Version 1.1[/italic cyan]\n"
                f"[dim]GitHub: https://github.com/RazeBerry/FrenchVocab/tree/main[/dim]",
                title="French Vocab Builder",
                border_style="bold green",
            )
        )

    def show_menu(self):
        console.print("\n[bold cyan]Menu Options:[/bold cyan]")
        console.print("1. Add a new word")
        console.print("2. Export to Anki deck")
        console.print("3. Reconcile LaTeX and Anki exports")
        console.print("4. Display all vocabulary")
        console.print("5. Exit")
        console.print(f"[bold green]Current word count: {self.entry_count}[/bold green]")
        choice = Prompt.ask("Choose an option", choices=["1", "2", "3", "4", "5"])
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
            
            # Normalize apostrophes
            word = word.replace("'", "'")
            
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
        # Accept all common apostrophe types: ' (straight), ' (right single quote), ' (left single quote)
        return all(char.isalpha() or char.isspace() or char in "'-''àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ" for char in word.strip())

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
        
        # Check if the English translation already has parentheses before adding them
        example_items = "".join(
            [f"    \\item {e[0]} \\\\ {e[1] if e[1].startswith('(') and e[1].endswith(')') else f'({e[1]})'}\n" for e in examples]
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
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            insert_position = content.rfind("\\entry")
            insert_position = content.find("\\end{itemize}", insert_position)

            updated_content = content[:insert_position] + new_entry + "\n\n" + content[insert_position:]

            with self.latex_file.open("w", encoding="utf-8") as file:
                file.write(updated_content)

            console.print(f"[bold green]Added/Updated entry for '{new_word}' in {self.latex_file}[/bold green]")
            normalized_new_word = self.normalize_word(new_word)
            self.normalized_entries[normalized_new_word] = new_word.capitalize()
        except FileNotFoundError:
            console.print(f"[bold red]Error: File not found - {self.latex_file}[/bold red]")
        except IOError as e:
            console.print(f"[bold red]Error reading from or writing to file: {e}[/bold red]")

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
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            entries_start = content.find("\\begin{itemize}[leftmargin=*]")
            entries_end = content.rfind("\\end{itemize}")

            if entries_start == -1 or entries_end == -1:
                console.print("[bold red]Error: Could not find the entries section.[/bold red]")
                return

            header = content[:entries_start]
            entries_section = content[entries_start:entries_end]
            footer = content[entries_end:]

            entry_pattern = r"(\\entry\{.*?\}.*?(?=\\entry|\Z))"
            entries = re.findall(entry_pattern, entries_section, re.DOTALL)

            if not entries:
                console.print("[bold yellow]No entries found to alphabetize.[/bold yellow]")
                return

            sorted_entries = sorted(
                entries,
                key=lambda x: self.normalize_word(re.search(r"\\entry\{(.*?)\}", x).group(1))
            )

            sorted_entries_section = "\\begin{itemize}[leftmargin=*]\n" + "".join(sorted_entries)

            sorted_content = header + sorted_entries_section + footer
            if len(sorted_content) < len(content) * 0.9:
                console.print("[bold red]Warning: Significant content loss detected. Aborting alphabetization.[/bold red]")
                return

            with self.latex_file.open("w", encoding="utf-8") as file:
                file.write(sorted_content)

            console.print("[bold green]Entries alphabetized successfully.[/bold green]")
        except FileNotFoundError:
            console.print(f"[bold red]Error: File not found - {self.latex_file}[/bold red]")
        except IOError as e:
            console.print(f"[bold red]Error reading from or writing to file: {e}[/bold red]")
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
                self.reconcile_menu_option()
            elif choice == "4":
                self.display_all_vocabulary()
            elif choice == "5":
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
        if word is None:  # User chose to abandon the edit
            return None

        latex_entry = self.format_latex_entry(word, word_type, definitions, examples)
        
        # Check if the latex_entry is empty or invalid
        if not self.is_valid_latex_entry(latex_entry):
            self.console.print("[bold red]Error: Generated LaTeX entry is empty or invalid. Aborting process.[/bold red]")
            return None

        self.display_latex_entry(latex_entry)
        self.insert_entry_alphabetically(latex_entry, word.capitalize())
        self.add_word_to_entries(word, ai_response)

        return word

    def is_valid_latex_entry(self, latex_entry: str) -> bool:
        # Check if the entry is not empty and contains the expected LaTeX structure
        return bool(latex_entry.strip()) and "\\entry{" in latex_entry and "}{" in latex_entry

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
            word_type: List[str],
            definitions: List[str],
            examples: List[Tuple[str, str]],
    ):
        table = Table(
            title=f"Information for [bold green]{word.capitalize()}[/bold green]"
        )
        table.add_column("Category", style="cyan", no_wrap=True)
        table.add_column("Information", style="magenta")

        word_type_str = ", ".join(word_type)
        table.add_row("Word Type", word_type_str)

        def_str = "\n".join([f"• {d}" for d in definitions])
        table.add_row("Definitions", def_str)

        # Check if the English translation already has parentheses
        ex_str = "\n".join([f"• {f}\n  {e if e.startswith('(') and e.endswith(')') else f'({e})'}" for f, e in examples])
        table.add_row("Examples", ex_str)

        console.print(table)

    def display_latex_entry(self, latex_entry: str):
        console.print(
            Panel(latex_entry, title="Generated LaTeX Entry", border_style="bold blue")
        )

    def get_all_latex_entries(self) -> Set[str]:
        # Return a set of all words in the LaTeX file, including incomplete entries
        all_entries = set()
        with self.latex_file.open("r", encoding="utf-8") as file:
            content = file.read()
        entries = re.findall(r"\\entry\{(.*?)\}", content)
        return set(entry.lower() for entry in entries)

    def get_all_exported_words(self) -> Set[str]:
        return set(self.exported_words)

    def compare_entries_and_exports(self) -> Tuple[Set[str], Set[str]]:
        latex_entries = self.get_all_latex_entries()
        exported_words = self.get_all_exported_words()
        in_latex_not_exported = latex_entries - exported_words
        in_exports_not_latex = exported_words - latex_entries
        return in_latex_not_exported, in_exports_not_latex

    def generate_discrepancy_report(self):
        in_latex_not_exported, in_exports_not_latex = self.compare_entries_and_exports()
        
        table = Table(title="Discrepancy Report")
        table.add_column("Category", style="cyan")
        table.add_column("Words", style="magenta")
        
        table.add_row(
            "In LaTeX but not exported",
            ", ".join(sorted(in_latex_not_exported)) or "None"
        )
        table.add_row(
            "In exports but not in LaTeX",
            ", ".join(sorted(in_exports_not_latex)) or "None"
        )
        
        self.console.print(table)
        
        if not in_latex_not_exported and not in_exports_not_latex:
            self.console.print("[green]No discrepancies found![/green]")
        else:
            self.console.print("[yellow]Discrepancies found. Please review the report above.[/yellow]")

    def reconcile_menu_option(self):
        self.generate_discrepancy_report()
        # Optionally, add interactive options to resolve discrepancies

    def display_all_vocabulary(self):
        """Displays all vocabulary entries present in the LaTeX file in a paginated table format.
        
        This function retrieves all vocabulary entries from the LaTeX file, formats them
        into a Rich table, and displays them with pagination for better readability.
        """
        if not self.word_entries:
            self.console.print("[bold yellow]No vocabulary entries found in the LaTeX file.[/bold yellow]")
            return
        
        # Create a table to display the vocabulary entries
        table = Table(title=f"[bold blue]All Vocabulary Entries ({len(self.word_entries)} words)[/bold blue]")
        table.add_column("No.", style="cyan", justify="right")
        table.add_column("Word", style="green")
        table.add_column("Type", style="magenta")
        table.add_column("Definitions", style="yellow")
        
        # Sort entries alphabetically
        sorted_entries = sorted(self.word_entries.items(), key=lambda x: self.normalize_word(x[0]))
        
        # Add rows to the table
        for index, (word, entry) in enumerate(sorted_entries, 1):
            # Truncate definitions if too long
            definitions = entry["definitions"]
            if len(definitions) > 60:
                definitions = definitions[:57] + "..."
            
            table.add_row(
                str(index),
                entry["word"],
                entry["type"] if isinstance(entry["type"], str) else ", ".join(entry["type"]),
                definitions
            )
        
        # Display the table with pagination
        self.console.print(table)
        
        # Add filter/search option
        if Confirm.ask("Would you like to search for a specific word?", default=False):
            self.search_vocabulary()

    def search_vocabulary(self):
        """Allows searching for specific vocabulary entries by keyword."""
        search_term = Prompt.ask("Enter search term").lower()
        
        results = {}
        for word, entry in self.word_entries.items():
            if (search_term in word.lower() or 
                search_term in entry["definitions"].lower() or 
                (isinstance(entry["type"], str) and search_term in entry["type"].lower()) or
                (isinstance(entry["type"], list) and any(search_term in t.lower() for t in entry["type"]))):
                results[word] = entry
        
        if not results:
            self.console.print(f"[bold yellow]No results found for '{search_term}'.[/bold yellow]")
            return
        
        # Display search results
        table = Table(title=f"[bold blue]Search Results for '{search_term}' ({len(results)} matches)[/bold blue]")
        table.add_column("Word", style="green")
        table.add_column("Type", style="magenta")
        table.add_column("Definitions", style="yellow")
        
        for word, entry in sorted(results.items(), key=lambda x: self.normalize_word(x[0])):
            # Truncate definitions if too long
            definitions = entry["definitions"]
            if len(definitions) > 60:
                definitions = definitions[:57] + "..."
            
            table.add_row(
                entry["word"],
                entry["type"] if isinstance(entry["type"], str) else ", ".join(entry["type"]),
                definitions
            )
        
        self.console.print(table)
        
        # Offer to display full entry for a selected word
        if Confirm.ask("Would you like to see the full entry for any of these words?", default=False):
            word_to_view = Prompt.ask("Enter the word to view")
            word_to_view_lower = word_to_view.lower()
            if word_to_view_lower in self.word_entries:
                self.display_existing_entry(word_to_view_lower)
            else:
                matching_words = [w for w in self.word_entries.keys() 
                                 if self.normalize_word(w) == self.normalize_word(word_to_view)]
                if matching_words:
                    self.display_existing_entry(matching_words[0])
                else:
                    self.console.print(f"[bold red]Word '{word_to_view}' not found.[/bold red]")


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