import json
import os
import re
import unicodedata
from typing import List, Tuple, Optional, Dict, Set
import sys
import genanki
from rich.console import Console
from rich.progress import Progress
from rich.prompt import Prompt, Confirm
from enum import Enum, auto
from latex_templates import INITIAL_TEX_CONTENT, SAMPLE_ENTRY, FINAL_TEX_CONTENT, AI_PROMPT_TEMPLATE
import time
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
import keyring
import getpass
from keyring.errors import KeyringError
from pathlib import Path
from llm_client import GeminiClient, ProviderFactory
from models import WordEntry, normalize_word_key
from latex_repository import LatexRepository
import uuid
import struct
import hashlib

# Import the new translator class
from eng_to_fr_translator import EnglishToFrenchTranslator
from fr_to_eng_translator import FrenchToEnglishTranslator
from ui_helper import UIHelper

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
    def __init__(self, latex_file: Optional[str], provider: str = None, verbose: bool = False, client: Optional[GeminiClient] = None):
        init_start = time.time()
        
        self.console = Console()
        self.ui = UIHelper(self.console)  # Initialize UIHelper
        # Use pathlib for cross-platform file handling
        script_dir = Path(__file__).parent # Get the directory where the script is located

        if latex_file is None:
            self.latex_file = script_dir / self.DEFAULT_FILENAME # Base path on script directory
            self.eng_to_fr_latex_file = script_dir / EnglishToFrenchTranslator.DEFAULT_FILENAME # Base path on script directory
            self.fr_to_eng_latex_file = script_dir / FrenchToEnglishTranslator.DEFAULT_FILENAME
        else:
            self.latex_file = Path(latex_file)
            # Assume the Eng->Fr file lives alongside the main one if a path is given
            self.eng_to_fr_latex_file = self.latex_file.parent / EnglishToFrenchTranslator.DEFAULT_FILENAME
            self.fr_to_eng_latex_file = self.latex_file.parent / FrenchToEnglishTranslator.DEFAULT_FILENAME

        if not self.latex_file.exists():
            self.create_initial_tex_file()
        
        # Repository for LaTeX entries (balanced-brace parser)
        self.repo = LatexRepository(self.latex_file)

        self.max_word_length = 500
        self.word_entries: Dict[str, Dict] = {}
        self.normalized_entries: Dict[str, str] = {}
        self.config_file = "vocab_builder_config.json"
        
        # Initialize the LLM client (allow injection)
        self.client = client
        
        # Initialize translator attribute
        self.eng_to_fr_translator: Optional[EnglishToFrenchTranslator] = None
        self.fr_to_eng_translator: Optional[FrenchToEnglishTranslator] = None
        self.duplicate_resolution: Optional[Dict[str, str]] = None  # stores {'mode': 'merge'|'force', 'existing': <word>}

        # Determine provider early and set verbosity before key bootstrapping
        if provider is None:
            provider = ProviderFactory.default_provider()
        self.provider = provider.lower()
        self.verbose = verbose

        # Load configuration + init client only if not injected
        load_config_start = time.time()
        if self.client is None:
            self.load_config()
            try:
                self.client = ProviderFactory.create(self.provider)
                self.ui.success(f"{self.provider.capitalize()} client initialized successfully!")
            except Exception as e:
                self.ui.error(f"Error initializing {self.provider} client: {e}")
                sys.exit(1)
        load_config_end = time.time()
        
        # Removed duplicate load_config call
        
        load_entries_start = time.time()
        self.load_existing_entries()
        load_entries_end = time.time()
        
        self.exported_words_file = script_dir / "exported_words.json"
        self.exported_words = self.load_exported_words()
        self.entry_count = self.count_entries()
        
        # Initialize the Eng->Fr translator 
        if self.client:
             self.eng_to_fr_translator = EnglishToFrenchTranslator(
                 console=self.console,
                 client=self.client,
                 latex_file_path=self.eng_to_fr_latex_file
             )
             self.fr_to_eng_translator = FrenchToEnglishTranslator(
                 console=self.console,
                 client=self.client,
                 latex_file_path=self.fr_to_eng_latex_file
             )
        else:
             self.ui.error("Could not initialize EnglishToFrenchTranslator due to missing LLM client.")
             self.ui.error("Could not initialize FrenchToEnglishTranslator due to missing LLM client.")

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
            self.ui.success(f"Created initial LaTeX file: {self.latex_file}")
        except IOError as e:
            self.ui.error(f"Error creating initial LaTeX file: {e}")
            raise


    def load_config(self):
        """Load API key for the selected provider and set env var."""
        provider = getattr(self, 'provider', ProviderFactory.default_provider())
        if provider == 'gemini':
            env_var = 'GEMINI_API_KEY'
            keyring_name = 'gemini_api_key'
            provider_label = 'Gemini'
        elif provider == 'claude':
            env_var = 'ANTHROPIC_API_KEY'
            keyring_name = 'anthropic_api_key'
            provider_label = 'Anthropic Claude'
        else:
            env_var = 'GEMINI_API_KEY'
            keyring_name = 'gemini_api_key'
            provider_label = provider.capitalize()

        api_key = os.environ.get(env_var)
        if not api_key:
            try:
                api_key = keyring.get_password("french_vocab_builder", keyring_name)
            except KeyringError as e:
                self.ui.error(f"Error accessing keyring: {e}")
                api_key = None

        if not api_key or not self.is_valid_api_key(api_key):
            api_key = self.first_time_setup(provider)

        os.environ[env_var] = api_key
        self.ui.success(f"Valid {env_var} found and set for {provider_label}.")

    def is_valid_api_key(self, api_key):
        # Basic check for Gemini API key format
        if not api_key or len(api_key) < 32:
            return False
        
        # Optional: Perform a test API call here to verify the key works
        # Return True if the call succeeds, False otherwise
        return True

    def first_time_setup(self, provider: str):
        """Interactive first-time setup for API key based on provider."""
        provider = provider.lower()
        if provider == 'claude':
            env_var = 'ANTHROPIC_API_KEY'
            keyring_name = 'anthropic_api_key'
            guide = (
                "[bold yellow]No valid ANTHROPIC_API_KEY found. Let's set it up.[/bold yellow]\n\n"
                "To obtain an API key:\n"
                "1. Go to https://console.anthropic.com/\n"
                "2. Create or log into your account\n"
                "3. Generate a new API key"
            )
            prompt_text = "Enter your Anthropic API key: "
        else:
            env_var = 'GEMINI_API_KEY'
            keyring_name = 'gemini_api_key'
            guide = (
                "[bold yellow]No valid GEMINI_API_KEY found. Let's set it up.[/bold yellow]\n\n"
                "To obtain an API key:\n"
                "1. Go to https://ai.google.dev/\n"
                "2. Sign up or log in to your account\n"
                "3. Navigate to the API section and generate a new API key"
            )
            prompt_text = "Enter your Gemini API key: "

        self.ui.panel(guide, title="API Key Setup", border_style="yellow")
        
        while True:
            api_key = getpass.getpass(prompt_text)
            if self.is_valid_api_key(api_key):
                try:
                    keyring.set_password("french_vocab_builder", keyring_name, api_key)
                    self.ui.success("API key saved securely.")
                    return api_key
                except KeyringError as e:
                    self.ui.error(f"Error saving to keyring: {e}")
                    if Confirm.ask("Do you want to continue without saving to keyring?"):
                        return api_key
            else:
                self.ui.error("Invalid API key. Please try again.")

    def get_llm_client(self):
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
            self.ui.error(f"File not found - {self.latex_file}")
            return 0
        except Exception as e:
            self.ui.error(f"Error reading file: {e}")
            return 0



    def load_existing_entries(self):
        """Loads existing vocabulary entries using a balanced-brace parser."""
        self.word_entries.clear()
        self.normalized_entries.clear()
        entries = self.repo.load_entries()
        key_collisions: Dict[str, List[str]] = {}
        for e in entries:
            if not e.word.strip() or not e.type or not e.definitions or not e.examples:
                self.ui.warning(f"Skipping entry due to content: '{e.word or '[EMPTY WORD]'}'")
                continue
            key = e.word.strip().lower()
            if key in self.word_entries:
                key_collisions.setdefault(key, [self.word_entries[key]['word']]).append(e.word)
            self.word_entries[key] = {
                'word': e.word,
                'type': e.type,
                'definitions': "; ".join(e.definitions),
                'examples': "; ".join([f"{fr} ({en})" if en else fr for fr, en in e.examples]),
                'definitions_list': e.definitions,
                'examples_list': e.examples,
            }
            norm = self.normalize_word(key)
            self.normalized_entries[norm] = key
        if key_collisions:
            self.ui.panel(
                f"[bold yellow]WARNING:[/bold yellow] {len(key_collisions)} duplicate word key(s) detected during loading, resulting in {sum(len(v)-1 for v in key_collisions.values())} overwritten entries.\n"
                "The application uses the *last* encountered entry for each duplicate word.\n"
                "Please review your `.tex` file and remove redundant entries for:\n" +
                "\n".join([f" - Key: '{key}' (from words: {', '.join(words)})" for key, words in key_collisions.items()]),
                title="Duplicate Entries Found",
                border_style="yellow"
            )
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
        def stable_32(seed: str) -> int:
            """Return a deterministic 32-bit *signed* int for deck/model IDs."""
            h = hashlib.sha1(seed.encode()).digest()
            return struct.unpack(">I", h[:4])[0] & 0x7FFFFFFF  # keep positive

        def note_guid(word: str) -> str:
            """Return the exact same 128-bit GUID for this word every time."""
            return uuid.uuid5(uuid.NAMESPACE_URL, f"fr_vocab::{word.lower()}").hex
        
        # Define the model with a stable ID
        MODEL_ID = stable_32("FrenchVocabModel/v1")
        model = genanki.Model(
            MODEL_ID,
            'French Vocab Model v1',
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

        # Create a new Anki deck with a stable ID
        DECK_ID = stable_32(f"FrenchDeck::{deck_name}")
        deck = genanki.Deck(DECK_ID, deck_name)

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

                # Create a new Anki note with a stable GUID
                card_guid = note_guid(word)  # deterministic!
                note = genanki.Note(
                    model=model,
                    guid=card_guid,
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
        self.ui.panel(feedback, title="Export Summary", border_style="green")

    def check_duplicate(self, word: str) -> Optional[str]:
        normalized_word = self.normalize_word(word)
        return self.normalized_entries.get(normalized_word)

    def handle_duplicate(self, word: str, existing_word: str) -> bool:
        # Use the actual key from normalized_entries for consistency
        normalized_word = self.normalize_word(word)
        actual_existing_word = self.normalized_entries.get(normalized_word, existing_word) # Get the stored version

        warning_text = f"Duplicate Warning:\nWord '{word}' (normalized: '{normalized_word}') already exists in the dictionary as '{actual_existing_word}'."
        # Use a red border for higher visibility
        self.ui.panel(warning_text, title="Duplicate Found!", border_style="bold red")

        # Create options for the menu
        options = [
            ("s", "Skip: Don't add this word and return to the main menu."),
            ("v", "View: Display the existing entry and return to the main menu."),
            ("m", "Merge: Append AI definitions/examples into the existing entry."),
            ("f", "Force add as a variant entry (will create a new entry)."),
        ]

        self.ui.display_menu("Please choose an action", options, show_numbers=False)

        choice = Prompt.ask("Your choice", choices=["s", "v", "m", "f"], default="s")

        if choice == "s":
            self.ui.panel("Skipping this word. Returning to main menu.", border_style="green")
            return False
        elif choice == "v":
            self.ui.panel(f"Displaying existing entry for '{actual_existing_word}':", border_style="cyan")
            # Ensure you use the correct key to retrieve the entry
            self.display_existing_entry(actual_existing_word.lower()) # Use the lowercase version which should be the key
            
            # Changed: Don't make a recursive call, just return to main menu
            self.ui.panel("Displayed existing entry. Returning to main menu.", border_style="blue")
            return False # Return False, indicating not to add the word
        elif choice == "m":
            # Defer merging until after AI response is parsed
            self.duplicate_resolution = {"mode": "merge", "existing": actual_existing_word}
            self.ui.info("Will merge new AI content into the existing entry after parsing.")
            return True
        elif choice == "f":
            # Proceed to add; may need to create a unique variant label later
            self.duplicate_resolution = {"mode": "force", "existing": actual_existing_word}
            self.ui.info("Will force-add as a new variant entry.")
            return True

    def display_existing_entry(self, word: str):
        entry = self.word_entries[word.lower()]
        # Prefer structured lists if available
        defs = entry.get('definitions_list')
        exs = entry.get('examples_list')
        if not defs:
            defs = entry['definitions'].split('; ')
        if not exs:
            # Attempt to split gracefully
            exs = []
            for e in entry['examples'].split('; '):
                if ' (' in e and e.endswith(')'):
                    fr, en = e.rsplit(' (', 1)
                    exs.append((fr, en[:-1]))
        self.display_parsed_info(entry['word'], [entry['type']], defs, exs)

    
    def welcome_screen(self):
        # Determine which provider is being used
        provider_name = "Unknown"
        if isinstance(self.client, GeminiClient):
            provider_name = "Google Gemini"
        else:
            # Check for Claude client (use string comparison to avoid import errors)
            client_class_name = self.client.__class__.__name__
            if client_class_name == "ClaudeClient":
                provider_name = "Anthropic Claude"
            
        self.ui.panel(
            f"[bold blue]Welcome to the French Vocabulary LaTeX Builder![/bold blue]\n\n"
            f"This application helps you build a LaTeX document for French vocabulary.\n"
            f"You can input French words, and the AI will provide definitions and examples.\n\n"
            f"[bold green]Your current vocabulary library contains {self.entry_count} words.[/bold green]\n"
            f"[bold cyan]Using LLM provider: {provider_name}[/bold cyan]\n\n"
            f"[italic cyan]Version 1.2[/italic cyan]\n"
            f"[dim]GitHub: https://github.com/RazeBerry/FrenchVocab/tree/main[/dim]",
            title="French Vocab Builder",
            border_style="bold green"
        )

    def show_menu(self):
        eng_fr_count = 0
        if self.eng_to_fr_translator:
            eng_fr_count = self.eng_to_fr_translator.entry_count
        
        fr_eng_count = 0
        if self.fr_to_eng_translator:
            fr_eng_count = self.fr_to_eng_translator.entry_count
            
        options = [
            ("1", f"Add French word [dim]({self.entry_count} entries)[/dim]"),
            ("2", f"Translate English -> French [dim]({eng_fr_count} pairs)[/dim]"),
            ("3", f"Translate French -> English [dim]({fr_eng_count} pairs)[/dim]"),
            ("4", "Export French words to Anki"),
            ("5", "Reconcile Anki exports (Fr->En)"),
            ("6", "Display all French words"),
            ("q", "[bold yellow]Exit[/bold yellow]")
        ]
        
        self.ui.display_menu("Menu", options)
        
        # Update choices to include 'q'
        choice = Prompt.ask("Choose an option", choices=["1", "2", "3", "4", "5", "6", "q"], default="1")
        return choice

    def get_word_input(self) -> str:
        while True:
            word = input("\nEnter a French word or short expression (or 'q' to cancel): ").strip()
            
            if word.lower() == 'q':
                self.ui.warning("Input cancelled. Returning to main menu.")
                return ""
            
            # Normalize apostrophes: convert curly quotes to straight apostrophes
            word = word.replace("’", "'").replace("‘", "'")
            
            if len(word.split()) > 10:
                self.ui.error("Please enter a single word or short expression (max 10 words).")
            elif len(word) > self.max_word_length:
                self.ui.error(f"Input is too long. Please limit to {self.max_word_length} characters.")
            elif not word:
                self.ui.error("Input cannot be empty.")
            elif not self.is_valid_french_input(word):
                self.ui.error("Input contains invalid characters for French words.")
            else:
                return word

    def is_valid_french_input(self, word: str) -> bool:
        # Allow letters (including accented), spaces, hyphens, and apostrophes
        # Accept straight apostrophe U+0027 ('), and typographic apostrophes U+2019 (’), U+2018 (‘)
        valid_chars = set("-'") | {"’", "‘"}
        return all(char.isalpha() or char.isspace() or char in valid_chars for char in word.strip())

    def query_ai(self, word: str) -> str:
        client = self.get_llm_client()
        if not client:
            return "[bold red]Failed to initialize Gemini client. Please check your API key and try again.[/bold red]"
        
        prompt = AI_PROMPT_TEMPLATE.format(word=word)
        metrics = {} # Initialize metrics dictionary
        full_text = "" # Initialize full_text

        with Progress() as progress:
            task = progress.add_task("[cyan]Querying Gemini...", total=None)
            
            chunks = []
            generator = client.stream(prompt) # Get the generator

            try:
                while True: # Loop to consume the generator
                    try:
                        text = next(generator) # Get next chunk
                        chunks.append(text)
                        progress.advance(task)
                    except StopIteration as e:
                        # Generator is exhausted, capture the return value (metrics)
                        metrics = e.value if e.value else {}
                        break # Exit the loop
            except Exception as e:
                # Catch potential errors during streaming itself
                self.ui.error(f"Error during Gemini stream: {e}")
                # Attempt to get metrics even if streaming errored mid-way
                # This assumes the generator's finally block still runs, which it should
                try:
                    # Force generator cleanup and potential return value retrieval
                    # We don't expect more text, just want the finally block to run
                    # A simple `list(generator)` would try to iterate again, causing issues.
                    # Calling `close()` might be appropriate if available/needed.
                    # For now, we assume StopIteration's value is the best bet.
                    pass # Metrics should have been captured in StopIteration
                except Exception as final_e:
                     self.ui.error(f"Error retrieving metrics after stream error: {final_e}")
                # Set default metrics if none were captured
                if not metrics:
                    metrics = {'ttft': -1, 'tps': -1, 'tokens_out': -1} # Indicate error state
                return "" # Return empty string on error
            finally:
                # Ensure progress bar completes if it hasn't
                 progress.update(task, completed=True)
                 
            full_text = "".join(chunks)

        # Display metrics if available
        self.ui.display_metrics(metrics)
             
        return full_text

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

    @staticmethod
    def format_latex_entry(
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
        # LaTeX escape helper (mirrors strategy used in eng_to_fr_translator)
        def escape_latex(text: str) -> str:
            if text is None:
                return ""
            mapping = {
                '&': r'\&',
                '%': r'\%',
                '$': r'\$',
                '#': r'\#',
                '_': r'\_',
                '{': r'\{',
                '}': r'\}',
                '~': r'\textasciitilde{}',
                '^': r'\textasciicircum{}',
                '\\': r'\textbackslash{}',
            }
            # Single-pass replacement over the original text only
            pattern = re.compile('|'.join(re.escape(k) for k in sorted(mapping.keys(), key=len, reverse=True)))
            return pattern.sub(lambda m: mapping[m.group(0)], text)

        # Capitalize and escape word and type
        capitalized_word = escape_latex(word.capitalize())
        escaped_type = escape_latex(word_type)

        # Escape definitions and examples
        def_items = "".join([f"    \\item {escape_latex(d)}\n" for d in definitions])

        example_lines = []
        for fr, en in examples:
            fr_esc = escape_latex(fr)
            en_esc = escape_latex(en)
            # Keep existing parentheses if already wrapped
            english_part = en_esc if (en_esc.startswith('(') and en_esc.endswith(')')) else f'({en_esc})'
            example_lines.append(f"    \\item {fr_esc} \\\\ {english_part}\n")
        example_items = "".join(example_lines)

        latex_entry = f"""\\entry{{{capitalized_word}}}{{{escaped_type}}}
      {{
    {def_items.rstrip()}
      }}
      {{
    {example_items.rstrip()}
      }}"""

        # Remove all square brackets (LLM sometimes wraps hints in [] )
        latex_entry = re.sub(r"\[|\]", "", latex_entry)

        return latex_entry

    def insert_entry_alphabetically(self, new_entry: str, new_word: str) -> None:
        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            last_entry_index = content.rfind("\\entry")
            if last_entry_index == -1:
                # No existing entries; place before \end{itemize} or \end{document}
                insert_position = content.rfind("\\end{itemize}")
                if insert_position == -1:
                    insert_position = content.rfind("\\end{document}")
                    if insert_position == -1:
                        insert_position = len(content)
            else:
                insert_position = content.find("\\end{itemize}", last_entry_index)
                if insert_position == -1:
                    insert_position = content.rfind("\\end{document}")
                    if insert_position == -1:
                        insert_position = len(content)

            updated_content = content[:insert_position] + new_entry + "\n\n" + content[insert_position:]

            with self.latex_file.open("w", encoding="utf-8") as file:
                file.write(updated_content)

            # Update the normalized entries dictionary after successful file write
            normalized_new_word = self.normalize_word(new_word)
            self.normalized_entries[normalized_new_word] = new_word.capitalize()
            
            self.ui.success(f"Added/Updated entry for '{new_word}' in {self.latex_file}")
        except FileNotFoundError:
            self.ui.error(f"File not found - {self.latex_file}")
        except IOError as e:
            self.ui.error(f"Error reading from or writing to file: {e}")

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

            # Find the main vocab list itemize (one that includes leftmargin option)
            itemize_header_match = re.search(r"\\begin{itemize}\[[^\]]*leftmargin[^\]]*\]", content, re.IGNORECASE)
            if not itemize_header_match:
                self.ui.error("Could not find the entries section.")
                return
            entries_start = itemize_header_match.start()
            header_line = itemize_header_match.group(0)
            entries_end = content.find("\\end{itemize}", itemize_header_match.end())

            if entries_end == -1:
                self.ui.error("Could not find the end of the entries section.")
                return

            header = content[:entries_start]
            entries_section = content[itemize_header_match.end():entries_end]
            footer = content[entries_end:]

            # Improved regex pattern that handles nested braces
            entry_pattern = r"""
                \\entry
                \{
                    (?P<word>[^{}]+)
                \}
                \{
                    (?P<type>[^{}]+)
                \}
                \{
                    (?P<defs> (?: [^{}]+ | \{[^{}]*\} )* )
                \}
                \{
                    (?P<exs>  (?: [^{}]+ | \{[^{}]*\} )* )
                \}
            """
            
            # Find all entries using the improved pattern
            entry_matches = list(re.finditer(entry_pattern, entries_section, re.VERBOSE | re.DOTALL))
            
            if not entry_matches:
                self.ui.warning("No entries found to alphabetize.")
                return
            
            # Extract full entry text and word for sorting
            entries = []
            for match in entry_matches:
                start, end = match.span()
                full_entry = entries_section[start:end]
                word = match.group('word')
                entries.append((word, full_entry))
            
            # Sort entries by normalized word
            sorted_entries = sorted(entries, key=lambda x: self.normalize_word(x[0]))
            
            # Reconstruct the entries section preserving original header line
            sorted_entries_section = header_line + "\n" + "\n\n".join([entry for _, entry in sorted_entries])

            sorted_content = header + sorted_entries_section + footer
            
            # Safety check to ensure we haven't lost content
            if len(sorted_content) < len(content) * 0.9:
                self.ui.error("Warning: Significant content loss detected. Aborting alphabetization.")
                return

            with self.latex_file.open("w", encoding="utf-8") as file:
                file.write(sorted_content)

            self.ui.success("Entries alphabetized successfully.")
        except FileNotFoundError:
            self.ui.error(f"File not found - {self.latex_file}")
        except IOError as e:
            self.ui.error(f"Error reading from or writing to file: {e}")

    def exit_screen(self):
        self.ui.panel(
            "[bold blue]Thank you for using the French Vocabulary LaTeX Builder![/bold blue]\n\n"
            "Your LaTeX file has been updated with the new entries.",
            title="Goodbye!",
            border_style="bold green"
        )

    def remove_accents(self, input_str):
        nfkd_form = unicodedata.normalize("NFKD", input_str)
        return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

    def run(self):
        self.welcome_screen()
        while True:
            self.entry_count = self.count_entries()
            if self.eng_to_fr_translator: # Refresh count if initialized
                 self.eng_to_fr_translator.entry_count = len(self.eng_to_fr_translator.eng_fr_pairs)
            if self.fr_to_eng_translator: # Refresh count if initialized
                 self.fr_to_eng_translator.entry_count = len(self.fr_to_eng_translator.fr_eng_pairs)
            choice = self.show_menu()
            if choice == "1":
                self.handle_new_word_entry()
            elif choice == "2":
                if self.eng_to_fr_translator:
                    self.eng_to_fr_translator.run()
                else:
                    self.ui.error("English-to-French translator is not available (initialization failed).")
            elif choice == "3":
                if self.fr_to_eng_translator:
                    self.fr_to_eng_translator.run()
                else:
                    self.ui.error("French-to-English translator is not available (initialization failed).")
            elif choice == "4":
                self.handle_anki_export()
            elif choice == "5":
                self.reconcile_menu_option()
            elif choice == "6":
                self.display_all_vocabulary()
            elif choice == "q":
                self.exit_screen()
                break
            input("\nPress Enter to continue...")

    def handle_new_word_entry(self):
        # Reset duplicate resolution per new flow
        self.duplicate_resolution = None
        original_word = self.get_word_input()
        if not original_word:
            return # User cancelled input

        # --- Stage 1 Duplicate Check (User Input) ---
        existing_word_check1 = self.check_duplicate(original_word)
        if existing_word_check1:
            if not self.handle_duplicate(original_word, existing_word_check1):
                self.ui.warning(f"Skipping '{original_word}' due to duplicate check (Stage 1).")
                return # User chose to skip or view existing entry

        # --- Query AI ---
        ai_response = self.query_ai(original_word)
        if not ai_response:
            self.ui.error(f"Failed to get information for '{original_word}'. Skipping this entry.")
            return

        # --- Spelling Check and Final Word Determination ---
        final_word = self.check_spelling(original_word, ai_response)
        if final_word is None: # User chose to abandon the edit during spelling check
            self.ui.warning(f"Abandoning entry for '{original_word}'.")
            return
        
        # --- Stage 2 Duplicate Check (Final/Corrected Word) ---
        # Check again only if the final word is different from the original input (case-insensitive)
        # and it wasn't the word found in the first check (if any)
        if final_word.lower() != original_word.lower() and not (self.duplicate_resolution and self.duplicate_resolution.get('mode') in ('merge','force')):
            existing_word_check2 = self.check_duplicate(final_word)
            if existing_word_check2 and existing_word_check2 != existing_word_check1:
                self.ui.info(f"Performing second duplicate check for corrected word '{final_word}'...")
                if not self.handle_duplicate(final_word, existing_word_check2):
                    self.ui.warning(f"Skipping '{final_word}' due to duplicate check (Stage 2).")
                    return # User chose to skip or view existing entry

        # --- Parse AI Response ---
        word_type, definitions, examples = self.parse_ai_response(ai_response)
        if not word_type or not definitions or not examples:
             self.ui.error("Failed to parse essential information from AI response. Aborting.")
             return

        # --- Display Parsed Info ---
        self.display_parsed_info(final_word, word_type, definitions, examples)

        # --- Merge path (if selected) ---
        if self.duplicate_resolution and self.duplicate_resolution.get('mode') == 'merge':
            target_key = self.duplicate_resolution.get('existing', final_word)
            self.merge_into_existing(target_key, word_type[0], definitions, examples)
            self.ui.success(f"Merged AI content into existing entry for '{target_key}'.")
            self.duplicate_resolution = None
            return

        # --- Format LaTeX Entry ---
        insert_word = final_word
        # If force mode and still colliding, create a unique variant
        if self.duplicate_resolution and self.duplicate_resolution.get('mode') == 'force':
            if self.check_duplicate(insert_word):
                insert_word = self.create_unique_variant(insert_word)
        latex_entry = self.format_latex_entry(insert_word, word_type[0], definitions, examples) # Use first element of word_type list

        # --- Validate LaTeX Entry ---
        if not self.is_valid_latex_entry(latex_entry):
            self.ui.error("Generated LaTeX entry is empty or invalid. Aborting process.")
            return

        # --- Display LaTeX Entry & Insert ---
        self.display_latex_entry(latex_entry)
        self.insert_entry_alphabetically(latex_entry, insert_word) # Insert using the (possibly variant) word

        # --- Update In-Memory Dictionaries ---
        self.add_word_to_entries(insert_word, word_type[0], definitions, examples) # Use first element of word_type list

        # --- Alphabetize ---
        self.alphabetize_entries()

        self.duplicate_resolution = None

        self.ui.success(f"Successfully processed and added entry for '{final_word}'.")

    def create_unique_variant(self, base_word: str) -> str:
        """Create a unique variant label for a duplicate word using hyphenated suffixes."""
        candidate = f"{base_word} - alt"
        if not self.check_duplicate(candidate):
            return candidate
        # Try alphabetical suffixes
        for suffix in 'abcdefghijklmnopqrstuvwxyz':
            candidate = f"{base_word} - alt {suffix}"
            if not self.check_duplicate(candidate):
                return candidate
        # Fallback with repeated 'alt'
        i = 2
        while True:
            candidate = f"{base_word} - alt x{i}"
            if not self.check_duplicate(candidate):
                return candidate
            i += 1

    def merge_into_existing(self, existing_word: str, new_type: str, new_defs: List[str], new_examples: List[Tuple[str, str]]):
        """Merge new definitions/examples into an existing entry and update the LaTeX file and memory."""
        key = existing_word.lower()
        if key not in self.word_entries:
            self.ui.error(f"Cannot merge: existing entry for '{existing_word}' not found.")
            return
        entry = self.word_entries[key]

        # Use structured lists if available else fallback
        defs_existing = entry.get('definitions_list') or [d.strip() for d in entry['definitions'].split('; ') if d.strip()]
        exs_existing = entry.get('examples_list') or []
        if not exs_existing and entry.get('examples'):
            for e in entry['examples'].split('; '):
                if ' (' in e and e.endswith(')'):
                    fr, en = e.rsplit(' (', 1)
                    exs_existing.append((fr, en[:-1]))

        # Dedup helpers
        def norm_text(s: str) -> str:
            return re.sub(r"\s+", " ", s).strip().lower()
        def norm_pair(p: Tuple[str,str]) -> Tuple[str,str]:
            return (norm_text(p[0]), norm_text(p[1]))

        merged_defs_map = {norm_text(d): d for d in defs_existing}
        for d in new_defs:
            nd = norm_text(d)
            if nd and nd not in merged_defs_map:
                merged_defs_map[nd] = d
        merged_defs = list(merged_defs_map.values())

        merged_exs_map = {norm_pair(p): p for p in exs_existing}
        for p in new_examples:
            np = norm_pair(p)
            if np not in merged_exs_map:
                merged_exs_map[np] = p
        merged_exs = list(merged_exs_map.values())

        # Keep existing type by default; if unknown, use new
        final_type = entry.get('type') or new_type
        # Rebuild LaTeX entry and replace in file
        latex_block = self.format_latex_entry(entry['word'], final_type, merged_defs, merged_exs)
        self.update_entry_in_file(entry['word'], latex_block)

        # Update memory
        entry['type'] = final_type
        entry['definitions_list'] = merged_defs
        entry['examples_list'] = merged_exs
        entry['definitions'] = "; ".join(merged_defs)
        entry['examples'] = "; ".join([f"{f} ({e})" for f,e in merged_exs])

    def update_entry_in_file(self, word_capitalized: str, new_block: str) -> None:
        """Replace the LaTeX entry block for the given word with new_block."""
        try:
            with self.latex_file.open("r", encoding="utf-8") as f:
                content = f.read()
            # Regex to match the specific entry by word with robust body matching
            pattern = r"""
                \\entry
                \{%(word)s\}
                \{[^{}]*\}
                \{ (?: [^{}]+ | \{[^{}]*\} )* \}
                \{ (?: [^{}]+ | \{[^{}]*\} )* \}
            """ % {"word": re.escape(word_capitalized)}
            new_content, n = re.subn(pattern, new_block, content, count=1, flags=re.VERBOSE | re.DOTALL)
            if n == 0:
                self.ui.warning(f"Could not locate LaTeX entry for '{word_capitalized}' to update. Skipping file update.")
                return
            with self.latex_file.open("w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            self.ui.error(f"Failed to update LaTeX entry for '{word_capitalized}': {e}")

    def is_valid_latex_entry(self, latex_entry: str) -> bool:
        # Check if the entry is not empty and contains the expected LaTeX structure
        return bool(latex_entry.strip()) and "\\entry{" in latex_entry and "}{" in latex_entry

    def check_spelling(self, word, ai_response):
        # More specific regex that stops at the next field and handles multiline content
        spelling_check_match = re.search(r'Spelling Check:\s*(.*?)(?=\nCorrectly Spelt Word:|$)', ai_response, re.DOTALL)
        spelling_check = spelling_check_match.group(1).strip() if spelling_check_match else None

        corrected_spelling_match = re.search(r'Correctly Spelt Word:\s*(.*?)(?=\nWord Type:|$)', ai_response, re.DOTALL)
        corrected_spelling = corrected_spelling_match.group(1).strip() if corrected_spelling_match else None
        
        # Debug: Print what was extracted (can be removed later)
        if corrected_spelling is not None:
            self.ui.debug(f"Extracted corrected spelling: '{corrected_spelling}'")
        
        # Validate the corrected spelling - check if it's empty, placeholder text, or same as input
        if corrected_spelling:
            # Remove common placeholder patterns
            if (corrected_spelling.startswith('[') and corrected_spelling.endswith(']')) or \
               not corrected_spelling.strip() or \
               corrected_spelling.lower().strip() == word.lower().strip():
                # Either placeholder text, empty, or same as input - no correction needed
                return word
            
            # Valid correction found that's different from input
            self.console.print(f"Did you mean '{corrected_spelling}' instead of '{word}'?")
            self.console.print("y: Yes, use the corrected spelling")
            self.console.print("n: No, keep the original spelling")
            self.console.print("q: Quit and abandon this edit")
            choice = Prompt.ask("Your choice", choices=["y", "n", "q"], default="y")
            
            if choice == "y":
                return corrected_spelling
            elif choice == "q":
                self.ui.warning("Abandoning edit. Returning to main menu.")
                return None
        
        return word

    def add_word_to_entries(self, word: str, word_type: str, definitions: List[str], examples: List[Tuple[str, str]]):
        """Updates the in-memory dictionaries with the new word entry."""
        word_lower = word.lower()
        self.word_entries[word_lower] = {
            "word": word.capitalize(),
            "type": word_type,
            "definitions": "; ".join(definitions),
            "examples": "; ".join([f"{f} ({e})" for f, e in examples]),
        }
        # Update normalized entries as well
        normalized_word = self.normalize_word(word_lower)
        self.normalized_entries[normalized_word] = word_lower
        self.entry_count = len(self.word_entries) # Keep count accurate

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
        word_type_str = ", ".join(word_type)
        self.ui.display_word_entry(word, word_type_str, definitions, examples)

    def display_latex_entry(self, latex_entry: str):
        self.ui.display_latex_entry(latex_entry)

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
        
        data = {
            "In LaTeX but not exported": ", ".join(sorted(in_latex_not_exported)) or "None",
            "In exports but not in LaTeX": ", ".join(sorted(in_exports_not_latex)) or "None"
        }
        
        self.ui.dict_to_table(data, title="Discrepancy Report")
        
        if not in_latex_not_exported and not in_exports_not_latex:
            self.ui.success("No discrepancies found!")
        else:
            self.ui.warning("Discrepancies found. Please review the report above.")

    def reconcile_menu_option(self):
        self.generate_discrepancy_report()
        # Offer one-click actions
        in_latex_not_exported, in_exports_not_latex = self.compare_entries_and_exports()
        # Export missing LaTeX words to Anki
        if in_latex_not_exported:
            if Confirm.ask(f"Export {len(in_latex_not_exported)} word(s) missing in Anki now?", default=True):
                deck_name = Prompt.ask("Enter deck name", default="French Vocabulary")
                self.export_to_anki(deck_name)
        # Remove extra exported words not present in LaTeX
        if in_exports_not_latex:
            if Confirm.ask(f"Remove {len(in_exports_not_latex)} stale exported word(s) from tracking?", default=False):
                self.exported_words.difference_update(in_exports_not_latex)
                self.save_exported_words()
                self.ui.success("Updated exported words; removed stale entries.")

    def display_all_vocabulary(self):
        """Displays all vocabulary entries present in the LaTeX file in a paginated table format.
        
        This function retrieves all vocabulary entries from the LaTeX file, formats them
        into a Rich table, and displays them with pagination for better readability.
        """
        if not self.word_entries:
            self.ui.warning("No vocabulary entries found in the LaTeX file.")
            return
        
        # Sort entries alphabetically
        sorted_entries = sorted(self.word_entries.items(), key=lambda x: self.normalize_word(x[0]))
        
        # Prepare data for table
        headers = ["No.", "Word", "Type", "Definitions"]
        rows = []
        
        for index, (word, entry) in enumerate(sorted_entries, 1):
            # Truncate definitions if too long
            definitions = entry["definitions"]
            if len(definitions) > 60:
                definitions = definitions[:57] + "..."
            
            rows.append([
                str(index),
                entry["word"],
                entry["type"] if isinstance(entry["type"], str) else ", ".join(entry["type"]),
                definitions
            ])
        
        # Display the table
        self.ui.quick_table(f"[bold blue]All Vocabulary Entries ({len(self.word_entries)} words)[/bold blue]", headers, rows)
        
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
            self.ui.warning(f"No results found for '{search_term}'.")
            return
        
        # Display search results
        headers = ["Word", "Type", "Definitions"]
        rows = []
        
        for word, entry in sorted(results.items(), key=lambda x: self.normalize_word(x[0])):
            # Truncate definitions if too long
            definitions = entry["definitions"]
            if len(definitions) > 60:
                definitions = definitions[:57] + "..."
            
            rows.append([
                entry["word"],
                entry["type"] if isinstance(entry["type"], str) else ", ".join(entry["type"]),
                definitions
            ])
        
        self.ui.quick_table(f"[bold blue]Search Results for '{search_term}' ({len(results)} matches)[/bold blue]", headers, rows)
        
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
                    self.ui.error(f"Word '{word_to_view}' not found.")


def main() -> None:
    start_time = time.time()
    
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description="French Vocabulary Builder")
    parser.add_argument('latex_file', nargs='?', help='Path to LaTeX file')
    parser.add_argument('--provider', choices=['gemini', 'claude'], 
                        help='LLM provider to use (gemini or claude)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose diagnostics output')
    args = parser.parse_args()
    
    latex_file = args.latex_file
    provider = args.provider  # Will be None if not specified
    verbose = bool(args.verbose)

    init_start = time.time()
    app = FrenchVocabBuilder(latex_file, provider, verbose=verbose)
    init_end = time.time()
    
    run_start = time.time()
    app.run()
    run_end = time.time()

    print(f"Total startup time: {init_end - start_time:.2f} seconds")
    print(f"Initialization time: {init_end - init_start:.2f} seconds")
    print(f"Run time: {run_end - run_start:.2f} seconds")

if __name__ == "__main__":
    main()
