import json
import os
import re
import shutil
import unicodedata
from typing import List, Tuple, Optional, Dict, Set
import sys
import genanki
from rich.console import Console
from rich.progress import Progress
from rich.prompt import Prompt, Confirm
from enum import Enum, auto
from cli.menu import main_menu_loop
from anki_exporter import AnkiExporter, AnkiExportEntry, latex_to_anki_format as latex_to_anki_html
from ai_response_parser import parse_ai_response_text
import time
import keyring
import getpass
from keyring.errors import KeyringError
from pathlib import Path
from llm_client import GeminiClient, ProviderFactory
from latex_repository import LatexRepository
from models import normalize_word_key
from languages import LanguageConfig, TranslatorConfig, default_language_code, get_language_config
from languages.anki_shared_styles import compute_template_hash

from .translator import TranslatorCLI
from ui_helper import UIHelper, read_line

class WordType(Enum):
    NOUN = auto()
    VERB = auto()
    ADJECTIVE = auto()
    ADVERB = auto()
    EXPRESSION = auto()
    PRONOMINAL_VERB = auto()
    OTHER = auto()


class FrenchVocabBuilder:
    DEFAULT_LANGUAGE_CONFIG = get_language_config(None)
    DEFAULT_LANGUAGE_CODE = default_language_code()
    DEFAULT_FILENAME = DEFAULT_LANGUAGE_CONFIG.vocab_filename
    language_config: LanguageConfig = DEFAULT_LANGUAGE_CONFIG
    language_code: str = DEFAULT_LANGUAGE_CODE

    def __init__(
        self,
        latex_file: Optional[str],
        provider: str = None,
        verbose: bool = False,
        client: Optional[GeminiClient] = None,
        language: Optional[str] = None,
        language_config: Optional[LanguageConfig] = None,
    ):
        init_start = time.time()

        if language and language_config:
            raise ValueError("Provide either language or language_config, not both.")

        if language_config is None:
            resolved_language = language or self.DEFAULT_LANGUAGE_CODE
            language_config = get_language_config(resolved_language)

        self.language_config = language_config
        self.language_code = language_config.code
        self.vocab_template = language_config.vocab
        entry_command = self.vocab_template.entry_command or "\\entry"
        if not entry_command.startswith("\\"):
            entry_command = f"\\{entry_command}"
        self.entry_command = entry_command

        self.console = Console()
        self.ui = UIHelper(self.console)  # Initialize UIHelper
        # Determine project root (one level above this module)
        module_dir = Path(__file__).resolve().parent
        project_root = module_dir.parent
        self.project_root = project_root

        self.default_vocab_filename = self.language_config.vocab_filename
        if latex_file is None:
            self.latex_file = project_root / self.default_vocab_filename
            self.eng_to_fr_latex_file = project_root / self.language_config.eng_to_target_filename
            self.fr_to_eng_latex_file = project_root / self.language_config.target_to_eng_filename
        else:
            self.latex_file = Path(latex_file)
            # Assume the Eng->Fr file lives alongside the main one if a path is given
            base_dir = self.latex_file.parent
            self.eng_to_fr_latex_file = base_dir / self.language_config.eng_to_target_filename
            self.fr_to_eng_latex_file = base_dir / self.language_config.target_to_eng_filename

        if not self.latex_file.exists():
            self.create_initial_tex_file()

        # Repository for LaTeX entries (balanced-brace parser)
        self.repo = LatexRepository(self.latex_file, entry_command=self.entry_command)

        # Allow longer phrases before triggering the length check
        self.max_word_length = 1000  # default max characters (overridable)
        self.max_words: Optional[int] = None  # unlimited by default; overridable
        self._entry_count_snapshot: Optional[tuple[float, int, int]] = None  # (mtime, size, count)
        self.allow_sentence_punctuation: bool = True  # allow punctuation by default
        self.route_sentences: bool = True  # default: route sentences to Fr->En translator
        self.sentence_examples_in_vocab: bool = False  # default: omit examples for sentences
        self.word_entries: Dict[str, Dict] = {}
        self.normalized_entries: Dict[str, str] = {}
        self.config_file = "vocab_builder_config.json"
        
        # Initialize the LLM client (allow injection)
        self.client = client
        
        # Apply optional runtime settings (env/config overrides)
        self._load_input_limits()

        # Initialize translator attribute
        self.eng_to_fr_translator: Optional[TranslatorCLI] = None
        self.fr_to_eng_translator: Optional[TranslatorCLI] = None
        self.duplicate_resolution: Optional[Dict[str, str]] = None  # stores {'mode': 'merge'|'force', 'existing': <word>}
        self.pending_spelling_suggestion: Optional[Dict[str, str]] = None

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
        
        self.exported_words_file = self._resolve_exported_words_path(project_root, self.latex_file.parent)
        self.exported_words, self.exported_deck_version = self.load_exported_words()
        self.entry_count = self.count_entries()
        
        # Initialize the Eng->Fr translator 
        if self.client:
             eng_to_target = self.language_config.eng_to_target
             target_to_eng = self.language_config.target_to_eng

             self.eng_to_fr_translator = TranslatorCLI(
                 console=self.console,
                 client=self.client,
                 config=eng_to_target,
                 latex_file_path=self.eng_to_fr_latex_file,
             )
             self.fr_to_eng_translator = TranslatorCLI(
                 console=self.console,
                 client=self.client,
                 config=target_to_eng,
                 latex_file_path=self.fr_to_eng_latex_file,
             )
        else:
             self.ui.error("Could not initialize EnglishToFrenchTranslator due to missing LLM client.")
             self.ui.error("Could not initialize FrenchToEnglishTranslator due to missing LLM client.")

        init_end = time.time()
        if self.verbose:
            self.console.print(
                f"Total init time: {init_end - init_start:.5f} seconds\n"
                f"  Load config time: {load_config_end - load_config_start:.5f} seconds\n"
                f"  Load entries time: {load_entries_end - load_entries_start:.5f} seconds"
            )

    def _ui_text(self, key: str, fallback: str) -> str:
        strings = getattr(self.language_config, "ui_strings", {}) or {}
        return strings.get(key, fallback)

    def _translator_title(self, config: TranslatorConfig) -> str:
        title = getattr(config, "ui_title", None)
        if title:
            return title
        source = getattr(config, "source_label", "Source")
        target = getattr(config, "target_label", "Target")
        return f"{source} → {target} Translator"

    def _resolve_exported_words_path(self, project_root: Path, target_dir: Path) -> Path:
        """Resolve the exported words tracker, preferring the LaTeX file's directory."""
        lang_code = self.language_code
        candidate = target_dir / f"exported_words_{lang_code}.json"
        if candidate.exists():
            return candidate

        def _fallback_candidates() -> List[Path]:
            paths: List[Path] = []
            paths.append(project_root / f"exported_words_{lang_code}.json")
            if lang_code == self.DEFAULT_LANGUAGE_CODE:
                paths.append(project_root / "exported_words.json")
            return paths

        for legacy_path in _fallback_candidates():
            if not legacy_path.exists():
                continue
            if legacy_path.parent == target_dir:
                return legacy_path
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(legacy_path, candidate)
                return candidate
            except OSError:
                return legacy_path

        return candidate

    def _entry_command(self) -> str:
        entry_cmd = getattr(self, "entry_command", self.DEFAULT_LANGUAGE_CONFIG.vocab.entry_command)
        if not entry_cmd.startswith('\\'):
            entry_cmd = f"\\{entry_cmd}"
        return entry_cmd

    def detect_input_type(self, text: str) -> str:
        """Classify input as 'word', 'expression', or 'sentence' using simple heuristics."""
        if not text:
            return 'word'
        t = text.strip()
        # Newlines strongly indicate sentence text
        if '\n' in t:
            return 'sentence'
        # Sentence-ending punctuation or long length
        if any(p in t for p in '.!?;:') or len(t) > 120:
            return 'sentence'
        # Word count thresholds
        wc = len(t.split())
        if wc >= 9:
            return 'sentence'
        if wc >= 2:
            return 'expression'
        return 'word'

    def create_initial_tex_file(self):
        try:
            template = getattr(self, "vocab_template", self.DEFAULT_LANGUAGE_CONFIG.vocab)
            # Create the parent directory if needed (only if not in the current directory)
            if self.latex_file.parent != Path('.'):
                self.latex_file.parent.mkdir(parents=True, exist_ok=True)
            with self.latex_file.open('w', encoding='utf-8') as file:
                file.write(template.initial_content)
                sample = template.sample_entry or ""
                if sample:
                    file.write(sample)
                file.write(template.final_content)
            self.ui.success(f"Created initial LaTeX file: {self.latex_file}")
        except IOError as e:
            self.ui.error(f"Error creating initial LaTeX file: {e}")
            raise

    def _load_input_limits(self) -> None:
        """Load UI/input and routing options from env or optional JSON config.

        Priority: defaults < config file < environment variables.
        - Env vars: FRENCH_VOCAB_MAX_CHARS, FRENCH_VOCAB_MAX_WORDS
        - Config file (JSON): {"input_limits": {"max_chars": int, "max_words": int|null}}
        Any non-positive or null max_words disables the word-count limit.
        """
        # 1) Config file (optional)
        try:
            from pathlib import Path as _Path
            cfg_path = _Path(__file__).parent / str(self.config_file)
            if cfg_path.exists():
                with cfg_path.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                limits = (data or {}).get('input_limits', {})
                if isinstance(limits, dict):
                    if 'max_chars' in limits:
                        try:
                            mc = int(limits['max_chars'])
                            if mc > 0:
                                self.max_word_length = mc
                        except (ValueError, TypeError):
                            pass
                    if 'max_words' in limits:
                        try:
                            mw = limits['max_words']
                            # allow null/None/<=0 to mean unlimited
                            if mw is None:
                                self.max_words = None
                            else:
                                mw_int = int(mw)
                                self.max_words = mw_int if mw_int > 0 else None
                        except (ValueError, TypeError):
                            pass
                    # sentence mode flag (optional)
                    if 'sentence_mode' in limits:
                        try:
                            sm = limits['sentence_mode']
                            if isinstance(sm, bool):
                                self.allow_sentence_punctuation = sm
                            elif isinstance(sm, str):
                                self.allow_sentence_punctuation = sm.strip().lower() in ("1", "true", "yes", "y", "on")
                        except Exception:
                            pass
                    # sentence routing (optional)
                    if 'route_sentences' in limits:
                        try:
                            rs = limits['route_sentences']
                            if isinstance(rs, bool):
                                self.route_sentences = rs
                            elif isinstance(rs, str):
                                self.route_sentences = rs.strip().lower() in ("1", "true", "yes", "y", "on")
                        except Exception:
                            pass
                    # include examples for sentences when kept in vocab
                    if 'sentence_examples' in limits:
                        try:
                            se = limits['sentence_examples']
                            if isinstance(se, bool):
                                self.sentence_examples_in_vocab = se
                            elif isinstance(se, str):
                                self.sentence_examples_in_vocab = se.strip().lower() in ("1", "true", "yes", "y", "on")
                        except Exception:
                            pass
        except Exception:
            # Be resilient; ignore config errors
            pass

        # 2) Environment variables (highest priority)
        try:
            env_chars = os.getenv('FRENCH_VOCAB_MAX_CHARS')
            if env_chars:
                ec = int(env_chars)
                if ec > 0:
                    self.max_word_length = ec
        except (ValueError, TypeError):
            pass
        try:
            env_words = os.getenv('FRENCH_VOCAB_MAX_WORDS')
            if env_words is not None:
                ew = int(env_words)
                self.max_words = ew if ew > 0 else None
        except (ValueError, TypeError):
            pass
        # sentence mode via env
        env_sentence = os.getenv('FRENCH_VOCAB_SENTENCE_MODE') or os.getenv('FRENCH_VOCAB_ALLOW_PUNCT')
        if env_sentence is not None:
            self.allow_sentence_punctuation = str(env_sentence).strip().lower() in ("1", "true", "yes", "y", "on")
        # routing and sentence examples
        env_route = os.getenv('FRENCH_VOCAB_ROUTE_SENTENCES')
        if env_route is not None:
            self.route_sentences = str(env_route).strip().lower() in ("1", "true", "yes", "y", "on")
        env_sent_ex = os.getenv('FRENCH_VOCAB_SENTENCE_EXAMPLES')
        if env_sent_ex is not None:
            self.sentence_examples_in_vocab = str(env_sent_ex).strip().lower() in ("1", "true", "yes", "y", "on")

    
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
                    if self.ui.confirm("Do you want to continue without saving to keyring?", default=False):
                        return api_key
            else:
                self.ui.error("Invalid API key. Please try again.")

    def get_llm_client(self):
        return self.client

    def load_exported_words(self) -> Tuple[Set[str], Optional[str]]:
        path = self.exported_words_file
        if path.exists():
            with path.open('r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                words = set(data.get("words", []))
                version = data.get("deck_version")
                return words, version
            if isinstance(data, list):
                return set(data), None
        return set(), None
    def save_exported_words(self):
        path = self.exported_words_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            pass
        with path.open('w', encoding='utf-8') as f:
            payload = {
                "words": sorted(self.exported_words),
                "deck_version": self.exported_deck_version,
            }
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def count_entries(self) -> int:
        try:
            stat = self.latex_file.stat()
        except FileNotFoundError:
            self.ui.error(f"File not found - {self.latex_file}")
            self._entry_count_snapshot = None
            return 0

        signature = (stat.st_mtime, stat.st_size)
        if (
            self._entry_count_snapshot is not None
            and self._entry_count_snapshot[0] == signature[0]
            and self._entry_count_snapshot[1] == signature[1]
        ):
            return self._entry_count_snapshot[2]

        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()
        except Exception as exc:
            self.ui.error(f"Error reading file: {exc}")
            return 0

        cmd_pattern = re.escape(self._entry_command()) + r"\{"
        count = len(re.findall(cmd_pattern, content))
        self._entry_count_snapshot = (signature[0], signature[1], count)
        return count



    def load_existing_entries(self):
        """Loads existing vocabulary entries using a balanced-brace parser."""
        self.word_entries.clear()
        self.normalized_entries.clear()
        entries = self.repo.load_entries()
        key_collisions: Dict[str, List[str]] = {}
        for e in entries:
            word = (e.word or "").strip()
            if not word:
                self.ui.warning(f"Skipping entry due to content: '{e.word or '[EMPTY WORD]'}'")
                continue

            if not e.definitions:
                self.ui.warning(f"Entry '{word}' is missing definitions; keeping it with an empty definition list.")
            if not e.examples:
                self.ui.warning(f"Entry '{word}' is missing examples; keeping it with an empty example list.")

            key = word.lower()
            if key in self.word_entries:
                key_collisions.setdefault(key, [self.word_entries[key]['word']]).append(e.word)
            definitions = list(e.definitions or [])
            examples = list(e.examples or [])
            self.word_entries[key] = {
                'word': word,
                'type': e.type or "",
                'definitions': "; ".join(definitions),
                'examples': "; ".join([f"{fr} ({en})" if en else fr for fr, en in examples]),
                'definitions_list': definitions,
                'examples_list': examples,
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
        return normalize_word_key(word)

    def latex_to_anki_format(self, text: str) -> str:
        """Delegate to the shared LaTeX→HTML conversion helper."""
        return latex_to_anki_html(text)

    def export_to_anki(
        self,
        deck_name: Optional[str] = None,
        include_exported_words: bool = False,
        *,
        selected_words: Optional[Set[str]] = None,
        auto_retry_on_empty: bool = True,
    ):
        """Exports the vocabulary entries to an Anki deck.

        This method creates an Anki deck using the genanki library by iterating over
        the current vocabulary entries, formatting each entry into an Anki note, and
        adding it to the deck. By default it only includes words that have not been
        exported before to avoid duplicates, but this behaviour can be overridden when
        rebuilding a deck from scratch or exporting a specific subset.

        Args:
            deck_name (str, optional): The name of the Anki deck to be created.
                Defaults to the deck name defined by the active language configuration.
            include_exported_words (bool): When True, previously exported words are
                also packaged into the deck (useful for rebuilding or migrating decks).
            selected_words (Optional[Set[str]]): Lower-case words to export exclusively.
            auto_retry_on_empty (bool): Internal flag to prevent infinite recursion when
                auto-retrying an export that produced zero cards.

        Raises:
            IOError: If there's an error writing the Anki package file.
        """
        deck_name = deck_name or self.language_config.anki.default_deck_name
        anki_config = self.language_config.anki
        template_version = getattr(anki_config, "version_id", None)
        if not template_version:
            template_version = compute_template_hash(
                [
                    {"name": tpl.name, "qfmt": tpl.question_format, "afmt": tpl.answer_format}
                    for tpl in anki_config.card_templates
                ],
                anki_config.card_css or "",
            )

        exporter = AnkiExporter(deck_name, anki_config)
        latex_words = set(self.word_entries.keys())
        all_exported_words = set(self.exported_words)
        include_all = include_exported_words
        auto_due_to_version = False

        if (
            selected_words is None
            and not include_all
            and template_version
            and self.exported_deck_version
            and template_version != self.exported_deck_version
        ):
            include_all = True
            auto_due_to_version = True

        entries_for_export: List[Tuple[str, str, AnkiExportEntry, bool]] = []

        for key, entry in self.word_entries.items():
            normalized_word = key.strip().lower()
            already_exported = normalized_word in all_exported_words
            if selected_words is not None:
                if key not in selected_words:
                    continue
            elif already_exported and not include_all:
                continue

            word_type = ', '.join(entry['type']) if isinstance(entry['type'], list) else entry['type']

            definitions_list = entry.get('definitions_list')
            if not definitions_list:
                definitions_source = entry.get('definitions', '')
                definitions_list = [d.strip() for d in re.split(r';\s*', definitions_source) if d.strip()]

            examples_list = entry.get('examples_list')
            if not examples_list:
                examples_list = []
                for example in re.split(r';\s*', entry.get('examples', '')):
                    example = example.strip()
                    if not example:
                        continue
                    if ' (' in example and example.endswith(')'):
                        fr, en = example.rsplit(' (', 1)
                        examples_list.append((fr, en[:-1]))
                    else:
                        examples_list.append((example, ''))

            export_entry = AnkiExportEntry(
                word=entry['word'],
                word_type=word_type,
                definitions=definitions_list,
                examples=examples_list,
            )
            entries_for_export.append((normalized_word, entry['word'], export_entry, already_exported))

        if not entries_for_export:
            if selected_words is not None:
                self.ui.warning("None of the selected words were found or eligible for export.")
                return
            if not self.word_entries:
                self.ui.warning("No vocabulary entries available to export.")
                return
            if include_all or not auto_retry_on_empty:
                self.ui.warning(
                    "No vocabulary entries qualified for Anki export. The generated deck will not contain any cards."
                )
                return
            self.ui.info(
                "No new words detected for export. Rebuilding deck with all tracked entries instead."
            )
            return self.export_to_anki(
                deck_name,
                include_exported_words=True,
                selected_words=selected_words,
                auto_retry_on_empty=False,
            )

        deck = exporter.build_deck([item[2] for item in entries_for_export])

        # Write the deck to a .apkg file
        output_path = Path(f"{deck_name}.apkg")
        if not output_path.is_absolute():
            output_path = output_path.resolve()
        export_directory = output_path.parent
        export_directory.mkdir(parents=True, exist_ok=True)
        self.ui.info(f"Anki deck export directory: {export_directory}")
        genanki.Package(deck).write_to_file(str(output_path))

        newly_added_words_normalized = set()
        newly_added_display = set()

        packaged_count = len(entries_for_export)

        for normalized_word, display_word, _, already_exported in entries_for_export:
            all_exported_words.add(normalized_word)
            if not already_exported:
                newly_added_words_normalized.add(normalized_word)
                newly_added_display.add(display_word)

        # Update the exported_words set and save it
        self.exported_words = all_exported_words
        self.exported_deck_version = template_version
        self.save_exported_words()

        # Prepare the feedback message for the user
        feedback = f"""
        [bold green]Anki deck '{deck_name}.apkg' created successfully![/bold green]
        [bold magenta]Deck file saved to: {output_path}[/bold magenta]
        [bold yellow]Export directory: {export_directory}[/bold yellow]

        [bold blue]Total words in deck: {len(all_exported_words)}[/bold blue]
        [bold cyan]Newly added words in this export: {len(newly_added_words_normalized)}[/bold cyan]
        [bold cyan]Words packaged in deck: {packaged_count}[/bold cyan]
        [bold cyan]Deck template version: {template_version or 'unknown'}[/bold cyan]

        New words added:
        {', '.join(sorted(newly_added_display, key=str.lower)) if newly_added_display else 'No new words added in this export.'}
        """

        if auto_due_to_version:
            feedback += (
                "\n[bold yellow]Detected template changes since the last export. "
                "A full deck rebuild was performed automatically.[/bold yellow]"
            )
        if selected_words is not None:
            feedback += "\n[bold yellow]Export limited to your selected vocabulary entries.[/bold yellow]"

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
            ("skip", "Skip — do not add this word."),
            ("view", "View the existing entry and return to the menu."),
            ("merge", "Merge new AI details into the existing entry."),
            ("force", "Force-add as a variant entry."),
        ]

        try:
            choice = self.ui.interactive_menu(
                "Duplicate Resolution",
                options,
                "Use ↑ and ↓ to choose how to handle the duplicate. Esc cancels.",
            )
        except KeyboardInterrupt:
            self.ui.warning("Duplicate handling cancelled. Returning to main menu.")
            return False

        if choice == "skip":
            self.ui.panel("Skipping this word. Returning to main menu.", border_style="green")
            return False
        elif choice == "view":
            self.ui.panel(f"Displaying existing entry for '{actual_existing_word}':", border_style="cyan")
            # Ensure you use the correct key to retrieve the entry
            self.display_existing_entry(actual_existing_word.lower()) # Use the lowercase version which should be the key
            
            # Changed: Don't make a recursive call, just return to main menu
            self.ui.panel("Displayed existing entry. Returning to main menu.", border_style="blue")
            return False # Return False, indicating not to add the word
        elif choice == "merge":
            # Defer merging until after AI response is parsed
            self.duplicate_resolution = {"mode": "merge", "existing": actual_existing_word}
            self.ui.info("Will merge new AI content into the existing entry after parsing.")
            return True
        elif choice == "force":
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
        # Determine which provider/model is being used
        provider_name = "Unknown"
        if self.client is not None:
            label_getter = getattr(self.client, "model_label", None)
            if callable(label_getter):
                try:
                    provider_name = label_getter()
                except Exception:
                    provider_name = self.client.__class__.__name__
            elif isinstance(self.client, GeminiClient):
                provider_name = f"Google Gemini ({self.client.MODEL_NAME})"
        else:
            provider_name = "No LLM configured"

        language_name = self.language_config.display_name
        app_title = self._ui_text("app.title", f"{language_name} Vocabulary LaTeX Builder")

        self.ui.panel(
            f"[bold blue]Welcome to the {app_title}![/bold blue]\n\n"
            f"This application helps you build a LaTeX document for {language_name} vocabulary.\n"
            f"You can input {language_name} words, and the AI will provide definitions and examples.\n\n"
            f"[bold green]Your current vocabulary library contains {self.entry_count} words.[/bold green]\n"
            f"[bold cyan]Using LLM provider: {provider_name}[/bold cyan]\n"
            f"[bold magenta]Active language: {language_name}[/bold magenta]\n\n"
            f"[italic cyan]Version 2.0[/italic cyan]\n"
            f"[dim]GitHub: https://github.com/RazeBerry/FrenchVocab/tree/main[/dim]",
            title=self._ui_text("app.panel_title", f"{language_name} Vocab Builder"),
            border_style="bold green"
        )

    def show_menu(self):
        eng_fr_count = 0
        if self.eng_to_fr_translator:
            eng_fr_count = self.eng_to_fr_translator.entry_count
        
        fr_eng_count = 0
        if self.fr_to_eng_translator:
            fr_eng_count = self.fr_to_eng_translator.entry_count
            
        exported_count = len(getattr(self, "exported_words", []))
        language_name = self.language_config.display_name
        add_word_label = self._ui_text("menu.add_word", f"Add {language_name} word")
        eng_to_cfg = self.language_config.eng_to_target
        target_to_cfg = self.language_config.target_to_eng
        eng_to_target_label = self._ui_text(
            "menu.eng_to_target",
            f"Translate {eng_to_cfg.source_label} -> {eng_to_cfg.target_label}",
        )
        target_to_eng_label = self._ui_text(
            "menu.target_to_eng",
            f"Translate {target_to_cfg.source_label} -> {target_to_cfg.target_label}",
        )

        display_all_label = self._ui_text("menu.display_all", f"Display all {language_name} words")

        options = [
            ("add", f"{add_word_label} [dim]({self.entry_count} entries)[/dim]"),
            ("eng_to_target", f"{eng_to_target_label} [dim]({eng_fr_count} pairs)[/dim]"),
            ("target_to_eng", f"{target_to_eng_label} [dim]({fr_eng_count} pairs)[/dim]"),
            ("anki_tools", f"Anki tools [dim]({exported_count} tracked exports)[/dim]"),
            ("display_vocab", display_all_label),
            ("exit", "[bold yellow]Exit[/bold yellow]"),
        ]

        try:
            return self.ui.interactive_menu(
                "Main Menu",
                options,
                "Use ↑ and ↓ to navigate. Press Enter to choose. Esc exits.",
            )
        except KeyboardInterrupt:
            return "exit"

    def show_anki_menu(self) -> str:
        """Display the nested Anki submenu and return the selected option."""
        in_latex_not_exported, in_exports_not_latex = self.compare_entries_and_exports()
        language_name = self.language_config.display_name
        export_label = self._ui_text("menu.anki_export", f"Export {language_name} words to Anki")
        reconcile_label = self._ui_text(
            "menu.anki_reconcile",
            f"Reconcile Anki exports ({self.language_config.target_to_eng.source_label} -> {self.language_config.target_to_eng.target_label})",
        )
        options = [
            ("export", f"{export_label} [dim](pending: {len(in_latex_not_exported)})[/dim]"),
            ("reconcile", f"{reconcile_label} [dim](extra: {len(in_exports_not_latex)})[/dim]"),
            ("back", "[bold yellow]Back to main menu[/bold yellow]"),
        ]

        try:
            return self.ui.interactive_menu(
                "Anki Tools",
                options,
                "Use ↑ and ↓ to navigate. Press Enter to select. Esc returns.",
            )
        except KeyboardInterrupt:
            return "back"

    def handle_anki_tools(self) -> bool:
        """Route to the requested Anki workflow.

        Returns True if an action was executed (so we pause afterwards), False if user went back.
        """
        choice = self.show_anki_menu()
        if choice == "export":
            self.handle_anki_export()
            return True
        if choice == "reconcile":
            self.reconcile_menu_option()
            return True
        self.ui.info("Returning to main menu without running Anki actions.")
        return False

    def get_word_input(self) -> str:
        """Read target-language text from the user, supporting multi-line input.

        Instructions:
        - Type/paste your text. Press Enter on an empty line to submit.
        - Enter 'q' on the first line to cancel.
        """
        lines = []
        first = True
        language_name = self.language_config.display_name
        first_prompt = f"\nEnter {language_name} text (word/phrase/sentence). Empty line to submit (or 'q' to cancel): "
        continuation_prompt = "Enter more text (or press Enter to finish): "
        while True:
            try:
                prompt = (
                    first_prompt
                    if first
                    else continuation_prompt
                )
                line = read_line(prompt)
            except EOFError:
                break

            # Allow cancel on the very first line
            if first and line.strip().lower() == 'q':
                self.ui.warning("Input cancelled. Returning to main menu.")
                return ""

            # Empty line after at least one line submits the entry
            if not line.strip() and not first:
                break

            lines.append(line)
            first = False

        word = "\n".join(lines).strip()

        # Normalize common typography quirks before validation
        word = unicodedata.normalize("NFC", word)
        word = word.replace("’", "'").replace("‘", "'")
        zero_width_chars = ("\u00AD", "\u200B", "\u200C", "\u200D", "\u2060", "\ufeff")
        for ch in zero_width_chars:
            if ch in word:
                word = word.replace(ch, "")

        # Basic validations
        if not word:
            self.ui.error("Input cannot be empty.")
            return ""
        if self.max_words is not None and len(word.split()) > self.max_words:
            self.ui.error(f"Please limit to {self.max_words} words.")
            return ""
        if len(word) > self.max_word_length:
            self.ui.error(f"Input is too long. Please limit to {self.max_word_length} characters.")
            return ""
        if not self.is_valid_input(word):
            self.ui.error(f"Input contains unsupported characters for {self.language_config.display_name} text.")
            return ""

        return word

    def is_valid_input(self, word: str) -> bool:
        """Validate user input using the active language configuration."""
        config = getattr(self, "language_config", self.DEFAULT_LANGUAGE_CONFIG)
        allow_sentences = getattr(self, 'allow_sentence_punctuation', False)
        return config.input_validator(word, allow_sentences)

    def is_valid_french_input(self, word: str) -> bool:
        """Backward-compatible alias relying on the active language validator."""
        return self.is_valid_input(word)

    def query_ai(self, word: str) -> str:
        provider_key = getattr(self, 'provider', ProviderFactory.default_provider())
        provider_label = provider_key.capitalize() if isinstance(provider_key, str) else 'Provider'

        client = self.get_llm_client()
        if not client:
            return f"[bold red]Failed to initialize {provider_label} client. Please check your API key and try again.[/bold red]"
        
        detected_type = self.detect_input_type(word)
        config = getattr(self, "language_config", self.DEFAULT_LANGUAGE_CONFIG)
        prompt_template = getattr(config, "prompt_template", None) or self.DEFAULT_LANGUAGE_CONFIG.prompt_template
        prompt = prompt_template.format(input_text=word, detected_type=detected_type)
        metrics = {} # Initialize metrics dictionary
        full_text = "" # Initialize full_text

        with Progress() as progress:
            task = progress.add_task(f"[cyan]Querying {provider_label}...", total=None)
            
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
                self.ui.error(f"Error during {provider_label} stream: {e}")
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
                self.ui.display_metrics(metrics)
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
        parsed = parse_ai_response_text(response)
        return parsed.word_type, parsed.definitions, parsed.examples

    @staticmethod
    def format_latex_entry(
            word: str,
            word_type: str,
            definitions: List[str],
            examples: List[Tuple[str, str]],
            entry_command: Optional[str] = None,
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

        # Determine which LaTeX command to use for entries
        entry_cmd = entry_command or FrenchVocabBuilder.DEFAULT_LANGUAGE_CONFIG.vocab.entry_command
        if not entry_cmd.startswith('\\'):
            entry_cmd = f"\\{entry_cmd}"

        # Capitalize and escape word and type
        capitalized_word = escape_latex(word if word_type.lower() == 'sentence' else word.capitalize())
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

        latex_entry = f"""{entry_cmd}{{{capitalized_word}}}{{{escaped_type}}}
      {{
    {def_items.rstrip()}
      }}
      {{
    {example_items.rstrip()}
      }}"""

        return latex_entry

    def insert_entry_alphabetically(self, new_entry: str, new_word: str) -> None:
        try:
            with self.latex_file.open("r", encoding="utf-8") as file:
                content = file.read()

            entry_cmd = self._entry_command()
            last_entry_index = content.rfind(entry_cmd)
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
            entry_cmd_pattern = re.escape(self._entry_command())
            entry_pattern = rf"""
                {entry_cmd_pattern}
                \s*\{{
                    (?P<word>[^{{}}]+)
                \}}
                \s*\{{
                    (?P<type>[^{{}}]+)
                \}}
                \s*\{{
                    (?P<defs> (?: [^{{}}]+ | \{{[^{{}}]*\}} )* )
                \}}
                \s*\{{
                    (?P<exs>  (?: [^{{}}]+ | \{{[^{{}}]*\}} )* )
                \}}
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
        language_name = self.language_config.display_name
        app_title = self._ui_text("app.title", f"{language_name} Vocabulary LaTeX Builder")
        self.ui.panel(
            f"[bold blue]Thank you for using the {app_title}![/bold blue]\n\n"
            "Your LaTeX file has been updated with the new entries.",
            title="Goodbye!",
            border_style="bold green"
        )

    def remove_accents(self, input_str):
        nfkd_form = unicodedata.normalize("NFKD", input_str)
        return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

    def run(self):
        main_menu_loop(self)

    def handle_new_word_entry(self):
        # Reset duplicate resolution per new flow
        self.duplicate_resolution = None
        self.pending_spelling_suggestion = None
        original_word = self.get_word_input()
        if not original_word:
            return # User cancelled input

        # --- Stage 1 Duplicate Check (User Input) ---
        existing_word_check1 = self.check_duplicate(original_word)
        if existing_word_check1:
            if not self.handle_duplicate(original_word, existing_word_check1):
                self.ui.warning(f"Skipping '{original_word}' due to duplicate check (Stage 1).")
                return # User chose to skip or view existing entry

        # Detect input type early (used to control downstream flow)
        detected_type = self.detect_input_type(original_word)

        # Optional intelligent routing: send sentences to Fr->En translator
        if detected_type == 'sentence' and getattr(self, 'route_sentences', True):
            target_filename = self.language_config.target_to_eng.default_filename
            route = self.ui.confirm(
                f"This looks like a full sentence. Translate and save in {target_filename} instead?",
                default=True,
            )
            if route:
                if not self.fr_to_eng_translator:
                    title = self._translator_title(self.language_config.target_to_eng)
                    self.ui.error(f"{title} is not available (initialization failed). Proceeding in vocab mode.")
                else:
                    # Perform translation and save via the translator
                    ok = self.fr_to_eng_translator.translate_and_save(original_word)
                    if ok is False:
                        self.ui.warning("Translation cancelled or failed.")
                    return

        # --- Query AI ---
        ai_response = self.query_ai(original_word)
        if not ai_response:
            self.ui.error(f"Failed to get information for '{original_word}'. Skipping this entry.")
            return

        # --- Spelling Check and Final Word Determination ---
        if detected_type == 'sentence':
            # For sentences, do not attempt to auto-correct; keep text as-is
            final_word = original_word
        else:
            final_word = self.check_spelling(original_word, ai_response)
        if final_word is None: # User chose to abandon the edit during spelling check
            preview = original_word.strip().replace('\n', ' ')
            if len(preview) > 80:
                preview = preview[:77] + '...'
            self.ui.warning(f"Abandoning entry for '{preview}'.")
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

        # Post-parse routing opportunity if AI identified as sentence
        if (word_type and isinstance(word_type, list) and word_type[0].lower() == 'sentence' and
            getattr(self, 'route_sentences', True)):
            title = self._translator_title(self.language_config.target_to_eng)
            route2 = self.ui.confirm(
                f"AI identified this as a sentence. Route to {title} instead?",
                default=True,
            )
            if route2:
                if not self.fr_to_eng_translator:
                    alt_title = self._translator_title(self.language_config.target_to_eng)
                    self.ui.error(f"{alt_title} is not available (initialization failed). Proceeding in vocab mode.")
                else:
                    ok = self.fr_to_eng_translator.translate_and_save(original_word)
                    if ok is False:
                        self.ui.warning("Translation cancelled or failed.")
                    return

        # If we keep sentence in vocab and examples are disabled, drop them
        if word_type and word_type[0].lower() == 'sentence' and not getattr(self, 'sentence_examples_in_vocab', False):
            examples = []

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
        latex_entry = self.format_latex_entry(
            insert_word,
            word_type[0],
            definitions,
            examples,
            entry_command=self.entry_command,
        )  # Use first element of word_type list

        # --- Validate LaTeX Entry ---
        if not self.is_valid_latex_entry(latex_entry):
            self.ui.error("Generated LaTeX entry is empty or invalid. Aborting process.")
            return

        # --- Display LaTeX Entry ---
        self.display_latex_entry(latex_entry)

        if self.pending_spelling_suggestion:
            original_word = self.pending_spelling_suggestion["original"]
            suggested_word = self.pending_spelling_suggestion["suggested"]
            use_corrected = self.ui.confirm(
                f"Use corrected spelling '{suggested_word}' instead of original '{original_word}'?",
                default=True,
            )
            if not use_corrected:
                self.ui.info(f"Reverting to original spelling '{original_word}'.")
                final_word = original_word
                insert_word = original_word
                if self.duplicate_resolution and self.duplicate_resolution.get('mode') == 'force':
                    if self.check_duplicate(insert_word):
                        insert_word = self.create_unique_variant(insert_word)
                latex_entry = self.format_latex_entry(
                    insert_word,
                    word_type[0],
                    definitions,
                    examples,
                    entry_command=self.entry_command,
                )
                self.display_latex_entry(latex_entry)
            else:
                final_word = suggested_word
            self.pending_spelling_suggestion = None

        # --- Confirm Save ---
        if not self.ui.confirm(
            f"Add this entry for '{insert_word}' to your vocabulary file?",
            default=True,
        ):
            self.ui.warning(f"Entry for '{insert_word}' discarded. Nothing saved.")
            self.duplicate_resolution = None
            return

        final_word = insert_word

        # --- Insert ---
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
        latex_block = self.format_latex_entry(
            entry['word'],
            final_type,
            merged_defs,
            merged_exs,
            entry_command=self.entry_command,
        )
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
            entry_cmd_pattern = re.escape(self._entry_command())
            word_pattern = re.escape(word_capitalized)
            pattern = rf"""
                {entry_cmd_pattern}
                \{{{word_pattern}\}}
                \{{[^{{}}]*\}}
                \{{ (?: [^{{}}]+ | \{{[^{{}}]*\}} )* \}}
                \{{ (?: [^{{}}]+ | \{{[^{{}}]*\}} )* \}}
            """
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
        entry_cmd = self._entry_command()
        return bool(latex_entry.strip()) and entry_cmd in latex_entry

    def check_spelling(self, word, ai_response):
        # More specific regex that stops at the next field and handles multiline content
        # Extract the spelling check section (value not used)
        # Keep for potential future diagnostics, but avoid unused variable warnings
        _ = re.search(r'Spelling Check:\s*(.*?)(?=\nCorrectly Spelt Word:|$)', ai_response, re.DOTALL)

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
            suggestion_panel = (
                "[bold]Original:[/bold] "
                f"[bold red]{word}[/bold red]\n"
                "[bold]Suggested:[/bold] "
                f"[bold green]{corrected_spelling}[/bold green]"
            )
            self.ui.panel(
                suggestion_panel,
                title="Spelling Suggestion",
                border_style="yellow",
                expand=False,
            )
            self.pending_spelling_suggestion = {
                "original": word,
                "suggested": corrected_spelling,
            }
            self.ui.info("Using suggested spelling for now; you can revert after the preview.")
            return corrected_spelling
        
        return word

    def add_word_to_entries(self, word: str, word_type: str, definitions: List[str], examples: List[Tuple[str, str]]):
        """Updates the in-memory dictionaries with the new word entry."""
        word_lower = word.lower()
        display_word = word if word_type.lower() == 'sentence' else word.capitalize()
        self.word_entries[word_lower] = {
            "word": display_word,
            "type": word_type,
            "definitions": "; ".join(definitions),
            "examples": "; ".join([f"{f} ({e})" for f, e in examples]),
            "definitions_list": list(definitions),
            "examples_list": list(examples),
        }
        # Update normalized entries as well
        normalized_word = self.normalize_word(word_lower)
        self.normalized_entries[normalized_word] = word_lower
        self.entry_count = len(self.word_entries) # Keep count accurate

    def handle_anki_export(self):
        default_deck = self.language_config.anki.default_deck_name
        mode_options = [
            ("incremental", "Incremental (new words only)"),
            ("rebuild", "Full rebuild (all words)"),
            ("selected", "Selected words"),
        ]
        try:
            export_mode = self.ui.interactive_menu(
                "Anki Export Mode",
                mode_options,
                "Choose how you want to export your vocabulary.",
            )
        except KeyboardInterrupt:
            self.ui.warning("Anki export cancelled.")
            return
        except Exception:
            export_mode = "incremental"

        deck_name = self.ui.prompt("Enter a name for your Anki deck", default=default_deck)

        selected_words: Optional[Set[str]] = None
        include_exported = False

        if export_mode == "rebuild":
            include_exported = True
        elif export_mode == "selected":
            selected_words = self._prompt_selected_words()
            if not selected_words:
                self.ui.warning("No matching words selected. Export cancelled.")
                return
            include_exported = True  # Ensure chosen entries are exported regardless of prior state.

        self.export_to_anki(
            deck_name,
            include_exported_words=include_exported,
            selected_words=selected_words,
        )
    
    def display_parsed_info(
            self,
            word: str,
            word_type: List[str],
            definitions: List[str],
            examples: List[Tuple[str, str]],
    ):
        word_type_str = ", ".join(word_type)
        self.ui.display_word_entry(word, word_type_str, definitions, examples)

    def _prompt_selected_words(self) -> Optional[Set[str]]:
        """Prompt the user to choose specific words for Anki export."""
        if not self.word_entries:
            self.ui.warning("No vocabulary entries available to select.")
            return None

        prompt_text = (
            "Enter the words you want to export separated by commas\n"
            "(matching is case-insensitive; leave blank to cancel)"
        )
        raw_input = self.ui.prompt(prompt_text).strip()
        if not raw_input:
            return None

        tokens = [token.strip() for token in raw_input.split(",")]
        selected_keys: Set[str] = set()
        missing: List[str] = []

        for token in tokens:
            if not token:
                continue
            lower_token = token.lower()
            if lower_token in self.word_entries:
                selected_keys.add(lower_token)
                continue

            normalized = self.normalize_word(lower_token)
            match = next(
                (key for key, entry in self.word_entries.items() if self.normalize_word(key) == normalized),
                None,
            )
            if match:
                selected_keys.add(match)
            else:
                missing.append(token)

        if missing:
            self.ui.warning(
                "The following words were not found and will be skipped: "
                + ", ".join(sorted(missing))
            )

        if not selected_keys:
            return None
        return selected_keys

    def display_latex_entry(self, latex_entry: str):
        self.ui.display_latex_entry(latex_entry)

    def get_all_latex_entries(self) -> Set[str]:
        # Return a set of all words in the LaTeX file, including incomplete entries
        with self.latex_file.open("r", encoding="utf-8") as file:
            content = file.read()
        entry_cmd_pattern = re.escape(self._entry_command()) + r"\{(.*?)\}"
        entries = re.findall(entry_cmd_pattern, content)
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
            if self.ui.confirm(f"Export {len(in_latex_not_exported)} word(s) missing in Anki now?", default=True):
                deck_name = self.ui.prompt("Enter deck name", default=self.language_config.anki.default_deck_name)
                self.export_to_anki(deck_name)
        # Remove extra exported words not present in LaTeX
        if in_exports_not_latex:
            if self.ui.confirm(f"Remove {len(in_exports_not_latex)} stale exported word(s) from tracking?", default=False):
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
        if self.ui.confirm("Would you like to search for a specific word?", default=False):
            self.search_vocabulary()

    def search_vocabulary(self):
        """Allows searching for specific vocabulary entries by keyword."""
        search_term = self.ui.prompt("Enter search term").strip().lower()
        
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
        if self.ui.confirm("Would you like to see the full entry for any of these words?", default=False):
            word_to_view = self.ui.prompt("Enter the word to view").strip()
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
