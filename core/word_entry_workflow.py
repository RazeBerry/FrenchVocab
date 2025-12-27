"""Word entry workflow orchestration.

This module handles the complete flow from user input to saved vocabulary entry,
including duplicate checking, AI querying, spelling correction, and persistence.
"""

import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from ai_response_parser import parse_ai_response_text
from languages import LanguageConfig, TranslatorConfig
from ui_helper import UIHelper, read_line

from .spelling_checker import SpellingChecker
from .history_logger import TranslationLogger

if TYPE_CHECKING:
    from .vocab_repository import VocabRepository
    from .llm_coordinator import LLMCoordinator
    from .translator import TranslatorCLI


class WordEntryWorkflow:
    """Orchestrates the complete word entry flow from input to save.

    This class encapsulates the ~250 line handle_new_word_entry() method
    into a focused, testable workflow with clear steps.
    """

    def __init__(
        self,
        vocab_repo: "VocabRepository",
        llm: "LLMCoordinator",
        ui: UIHelper,
        language_config: LanguageConfig,
        *,
        history_logger: Optional[TranslationLogger] = None,
        spelling_checker: Optional[SpellingChecker] = None,
        fr_to_eng_translator: Optional["TranslatorCLI"] = None,
        max_word_length: int = 1000,
        max_words: Optional[int] = None,
        allow_sentence_punctuation: bool = True,
        route_sentences: bool = True,
        sentence_examples_in_vocab: bool = False,
        entry_command: str = "\\entry",
        provider_label_fn: Optional[Callable[[], str]] = None,
        on_settings: Optional[Callable[[], None]] = None,
        on_entry_saved: Optional[Callable[[str], None]] = None,
        get_word_input_fn: Optional[Callable[[], str]] = None,
        # Additional callbacks for test compatibility
        query_ai_fn: Optional[Callable[[str], str]] = None,
        check_spelling_fn: Optional[Callable[[str, str], Optional[str]]] = None,
        parse_ai_response_fn: Optional[Callable[[str], Tuple[str, List[str], List[Tuple[str, str]]]]] = None,
        check_duplicate_fn: Optional[Callable[[str], Optional[str]]] = None,
        display_parsed_info_fn: Optional[Callable[[str, Any, List[str], List[Tuple[str, str]]], None]] = None,
        display_latex_entry_fn: Optional[Callable[[str], None]] = None,
        is_valid_latex_entry_fn: Optional[Callable[[str], bool]] = None,
        insert_entry_alphabetically_fn: Optional[Callable[[str, str], None]] = None,
        add_word_to_entries_fn: Optional[Callable[[str, str, List[str], List[Tuple[str, str]]], None]] = None,
    ):
        self.vocab_repo = vocab_repo
        self.llm = llm
        self.ui = ui
        self.language_config = language_config
        self.history_logger = history_logger
        self.spelling_checker = spelling_checker or SpellingChecker(ui)
        self.fr_to_eng_translator = fr_to_eng_translator
        self.max_word_length = max_word_length
        self.max_words = max_words
        self.allow_sentence_punctuation = allow_sentence_punctuation
        self.route_sentences = route_sentences
        self.sentence_examples_in_vocab = sentence_examples_in_vocab
        self.entry_command = entry_command
        self._provider_label_fn = provider_label_fn or (lambda: "AI")
        self._on_settings = on_settings
        self._on_entry_saved = on_entry_saved
        self._get_word_input_fn = get_word_input_fn

        # Callbacks for test compatibility - these override internal implementations
        self._query_ai_fn = query_ai_fn
        self._check_spelling_fn = check_spelling_fn
        self._parse_ai_response_fn = parse_ai_response_fn
        self._check_duplicate_fn = check_duplicate_fn
        self._display_parsed_info_fn = display_parsed_info_fn
        self._display_latex_entry_fn = display_latex_entry_fn
        self._is_valid_latex_entry_fn = is_valid_latex_entry_fn
        self._insert_entry_alphabetically_fn = insert_entry_alphabetically_fn
        self._add_word_to_entries_fn = add_word_to_entries_fn

        # Per-run state
        self.duplicate_resolution: Optional[Dict[str, str]] = None

    def run(self, ensure_llm_ready_fn: Callable[[], bool]) -> bool:
        """Execute the full word entry workflow.

        Args:
            ensure_llm_ready_fn: Function to check/initialize LLM. Returns True if ready.

        Returns:
            True if entry was saved, False otherwise.
        """
        if not ensure_llm_ready_fn():
            self.ui.info(
                "Returning to main menu without adding a word. "
                "Configure an AI provider to re-enable this flow."
            )
            return False

        # Load existing entries lazily so duplicate checks are accurate
        self.vocab_repo.ensure_entries_loaded()

        # Reset duplicate resolution per new flow
        self.duplicate_resolution = None

        # Use provided input function or default to _collect_input
        if self._get_word_input_fn:
            original_word = self._get_word_input_fn()
        else:
            original_word = self._collect_input()
        if not original_word:
            return False  # User cancelled input

        # Stage 1 Duplicate Check
        if self._check_duplicate_fn:
            existing_word_check1 = self._check_duplicate_fn(original_word)
        else:
            existing_word_check1 = self.vocab_repo.check_duplicate(original_word)
        if existing_word_check1:
            if not self._handle_duplicate(original_word, existing_word_check1):
                self.ui.warning(f"Skipping '{original_word}' due to duplicate check (Stage 1).")
                return False

        # Detect input type (used to control downstream flow)
        detected_type = self._detect_input_type(original_word)

        # Show non-blocking hint if sentence detected
        if detected_type == 'sentence' and self.route_sentences:
            target_filename = self.language_config.target_to_eng.default_filename
            self.ui.info(
                f"This looks like a sentence. After AI analysis, "
                f"you'll have the option to route it to {target_filename}.",
                accent="dim"
            )

        # Query AI
        if self._query_ai_fn:
            ai_response = self._query_ai_fn(original_word)
        else:
            ai_response = self._query_ai_with_recovery(original_word)
        if not ai_response:
            return False

        # Spelling check and final word determination
        if detected_type == 'sentence':
            final_word = original_word
        elif self._check_spelling_fn:
            final_word = self._check_spelling_fn(original_word, ai_response)
        else:
            final_word = self.spelling_checker.check(original_word, ai_response)

        if final_word is None:
            preview = original_word.strip().replace('\n', ' ')
            if len(preview) > 80:
                preview = preview[:77] + '...'
            self.ui.warning(f"Abandoning entry for '{preview}'.")
            return False

        # Stage 2 Duplicate Check (if word was corrected)
        if (final_word.lower() != original_word.lower() and
            not (self.duplicate_resolution and
                 self.duplicate_resolution.get('mode') in ('merge', 'force'))):
            if self._check_duplicate_fn:
                existing_word_check2 = self._check_duplicate_fn(final_word)
            else:
                existing_word_check2 = self.vocab_repo.check_duplicate(final_word)
            if existing_word_check2 and existing_word_check2 != existing_word_check1:
                self.ui.info(f"Performing second duplicate check for corrected word '{final_word}'...")
                if not self._handle_duplicate(final_word, existing_word_check2):
                    self.ui.warning(f"Skipping '{final_word}' due to duplicate check (Stage 2).")
                    return False

        # Parse AI response
        if self._parse_ai_response_fn:
            word_type, definitions, examples = self._parse_ai_response_fn(ai_response)
            parsing_warnings = []
        else:
            word_type, definitions, examples, parsing_warnings = self._parse_response(ai_response)

        # Graceful degradation: only fail if BOTH definitions and examples are missing
        if not definitions and not examples:
            self.ui.error(
                "Cannot add vocabulary entry: Failed to parse both definitions and examples from AI response."
            )
            if parsing_warnings:
                for warning in parsing_warnings:
                    self.ui.warning(warning)
            return False

        # Warn about partial parsing but continue
        if not definitions:
            self.ui.warning("Could not parse definitions from AI response. Saving with examples only.")
        if not examples:
            self.ui.warning("Could not parse examples from AI response. Saving with definitions only.")
        if parsing_warnings:
            for warning in parsing_warnings:
                if "Could not parse" not in warning:  # Avoid duplicate warnings
                    self.ui.info(warning, accent="dim")

        primary_word_type = word_type[0] if isinstance(word_type, list) else str(word_type or "")

        # Post-parse routing opportunity if AI identified as sentence
        if (isinstance(word_type, list) and
            primary_word_type.lower() == 'sentence' and
            self.route_sentences):
            if self._offer_sentence_routing(original_word, primary_word_type):
                return True  # Routed to translator, workflow complete

        # If keeping sentence in vocab and examples disabled, drop them
        if primary_word_type.lower() == 'sentence' and not self.sentence_examples_in_vocab:
            examples = []

        # Display parsed info
        if self._display_parsed_info_fn:
            self._display_parsed_info_fn(final_word, word_type, definitions, examples)
        else:
            self._display_parsed_info(final_word, word_type, definitions, examples)

        # Handle merge path if selected
        if self.duplicate_resolution and self.duplicate_resolution.get('mode') == 'merge':
            target_key = self.duplicate_resolution.get('existing', final_word)
            if self._handle_merge(target_key, primary_word_type, definitions, examples):
                self.ui.success(f"Merged AI content into existing entry for '{target_key}'.")
            self.duplicate_resolution = None
            return True

        # Prepare for save
        history_action = "new"
        history_existing_word: Optional[str] = None
        if self.duplicate_resolution:
            history_action = self.duplicate_resolution.get('mode', 'new')
            history_existing_word = self.duplicate_resolution.get('existing')

        # Format LaTeX entry
        insert_word = final_word
        if self.duplicate_resolution and self.duplicate_resolution.get('mode') == 'force':
            if self.vocab_repo.check_duplicate(insert_word):
                insert_word = self._create_unique_variant(insert_word)

        latex_entry = self.vocab_repo.format_latex_entry(
            insert_word,
            primary_word_type,
            definitions,
            examples,
            entry_command=self.entry_command,
        )

        if self._is_valid_latex_entry_fn:
            is_valid = self._is_valid_latex_entry_fn(latex_entry)
        else:
            is_valid = self.vocab_repo.is_valid_latex_entry(latex_entry)
        if not is_valid:
            self.ui.error("Cannot add vocabulary entry: Generated LaTeX is empty or invalid.")
            return False

        # Preview and confirm
        if self._display_latex_entry_fn:
            self._display_latex_entry_fn(latex_entry)
        else:
            self.ui.display_latex_entry(latex_entry)

        corrected_word_value = final_word if final_word != original_word else None

        if not self.ui.confirm(
            f"Add this entry for '{insert_word}' to your vocabulary file?",
            default=True,
        ):
            self.ui.warning(f"Entry for '{insert_word}' discarded. Nothing saved.")
            self.duplicate_resolution = None
            return False

        # Save entry
        self._save_entry(
            insert_word=insert_word,
            original_word=original_word,
            word_type=primary_word_type,
            definitions=definitions,
            examples=examples,
            latex_entry=latex_entry,
            history_action=history_action,
            history_existing_word=history_existing_word,
            corrected_word_value=corrected_word_value,
        )

        self.duplicate_resolution = None

        entry_count = len(self.vocab_repo.word_entries)
        self.ui.success(f"Entry saved successfully! ({entry_count - 1} {entry_count} entries)")

        if self._on_entry_saved:
            self._on_entry_saved(insert_word)

        # Show quick action menu
        return self._show_quick_actions()

    def _collect_input(self) -> str:
        """Read target-language text from the user."""
        language_name = self.language_config.display_name
        limit_descriptors: list[str] = []
        if self.max_words:
            limit_descriptors.append(f"{self.max_words} words")
        if self.max_word_length:
            limit_descriptors.append(f"{self.max_word_length} chars")
        limit_hint = f" [{' '.join(limit_descriptors)}]" if limit_descriptors else ""

        prompt = f"\nEnter {language_name} text{limit_hint} (Esc to cancel): "

        try:
            line = read_line(prompt)
        except (EOFError, KeyboardInterrupt):
            self.ui.warning("Input cancelled. Returning to main menu.")
            return ""

        # Treat any ESC sequence as an immediate cancel
        if line and "\x1b" in line:
            self.ui.warning("Input cancelled via Esc. Returning to main menu.")
            return ""

        word = line.strip()

        # Normalize common typography quirks before validation
        word = unicodedata.normalize("NFC", word)
        word = word.replace("'", "'").replace("'", "'")
        zero_width_chars = ("\u00AD", "\u200B", "\u200C", "\u200D", "\u2060", "\ufeff")
        for ch in zero_width_chars:
            if ch in word:
                word = word.replace(ch, "")

        # Basic validations
        if not word:
            self.ui.error("Cannot add vocabulary entry: input cannot be empty.")
            return ""
        if self.max_words is not None and len(word.split()) > self.max_words:
            self.ui.error(
                f"Cannot add vocabulary entry: please limit to {self.max_words} words."
            )
            return ""
        if len(word) > self.max_word_length:
            self.ui.error(
                f"Cannot add vocabulary entry: please limit to {self.max_word_length} characters."
            )
            return ""
        if not self._is_valid_input(word):
            self.ui.error(
                f"Cannot add vocabulary entry: input contains unsupported characters for "
                f"{self.language_config.display_name} text."
            )
            return ""

        return word

    def _is_valid_input(self, word: str) -> bool:
        """Validate user input using the active language configuration."""
        return self.language_config.input_validator(word, self.allow_sentence_punctuation)

    def _detect_input_type(self, text: str) -> str:
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

    def _query_ai_with_recovery(self, word: str) -> Optional[str]:
        """Query AI with recovery options on failure."""
        detected_type = self._detect_input_type(word)
        prompt_template = (
            getattr(self.language_config, "prompt_template", None) or
            self.language_config.prompt_template
        )
        prompt = prompt_template.format(input_text=word, detected_type=detected_type)

        def _on_exception(exc: Exception, label: str) -> bool:
            return self.llm.handle_ai_exception(
                exc=exc,
                provider_label=label,
                on_settings=self._on_settings,
            )

        response, _ = self.llm.query(
            prompt=prompt,
            progress_label=self._provider_label_fn(),
            on_exception=_on_exception,
        )

        if response:
            return response

        # Offer recovery options
        self.ui.error(
            f"Cannot add vocabulary entry: Failed to get AI response for '{word}'",
            with_panel=True
        )

        recovery_options = [
            ("retry", " Retry now"),
            ("settings", " Open Settings"),
            ("skip", " Return to main menu"),
        ]

        try:
            recovery_choice = self.ui.interactive_menu(
                "What would you like to do?",
                recovery_options,
                "Press Esc to return to main menu",
            )
        except KeyboardInterrupt:
            return None

        if recovery_choice == "retry":
            response, _ = self.llm.query(
                prompt=prompt,
                progress_label=self._provider_label_fn(),
                on_exception=_on_exception,
            )
            if not response:
                self.ui.warning("Retry failed. Returning to main menu.")
            return response
        elif recovery_choice == "settings":
            if self._on_settings:
                self._on_settings()
            if self.ui.confirm("Try querying AI again?", default=True):
                response, _ = self.llm.query(
                    prompt=prompt,
                    progress_label=self._provider_label_fn(),
                    on_exception=_on_exception,
                )
                if not response:
                    self.ui.warning("Query failed. Returning to main menu.")
                return response
        return None

    def _parse_response(
        self, response: str
    ) -> Tuple[List[str], List[str], List[Tuple[str, str]], List[str]]:
        """Parse the AI's response to extract word type, definitions, examples, and warnings."""
        parsed = parse_ai_response_text(response)
        return parsed.word_type, parsed.definitions, parsed.examples, parsed.parsing_warnings

    def _handle_duplicate(self, word: str, existing_word: str) -> bool:
        """Handle duplicate word detection with user interaction."""
        normalized_word = self.vocab_repo.normalize_word(word)
        actual_existing_word = self.vocab_repo.normalized_entries.get(
            normalized_word, existing_word
        )

        warning_text = (
            f"Duplicate Warning:\nWord '{word}' (normalized: '{normalized_word}') "
            f"already exists in the dictionary as '{actual_existing_word}'."
        )
        self.ui.panel(warning_text, title=" Duplicate Detected", border_style="yellow3")

        options = [
            ("view", " View existing entry first"),
            ("merge", " Merge - Combine new definitions into existing entry"),
            ("force", " Force - Save as variant (e.g., 'word - alt')"),
            ("skip", " Skip - Keep existing, discard new"),
        ]

        try:
            choice = self.ui.interactive_menu(
                "How should I handle this duplicate?",
                options,
                "Merge = 1 entry with all definitions  Force = 2 separate entries  Esc to cancel",
            )
        except KeyboardInterrupt:
            self.ui.warning("Duplicate handling cancelled. Returning to main menu.")
            return False

        if choice == "skip":
            self.ui.info("Skipping this word. Returning to main menu.")
            return False
        elif choice == "view":
            self.ui.panel(
                f"Displaying existing entry for '{actual_existing_word}':",
                border_style="cyan"
            )
            self._display_existing_entry(actual_existing_word.lower())
            self.ui.panel("Displayed existing entry. Returning to main menu.", border_style="blue")
            return False
        elif choice == "merge":
            self.duplicate_resolution = {"mode": "merge", "existing": actual_existing_word}
            self.ui.info(
                f"Will merge new definitions into existing '{actual_existing_word}'\n"
                f"  Result: 1 combined entry with all definitions"
            )
            return True
        elif choice == "force":
            self.duplicate_resolution = {"mode": "force", "existing": actual_existing_word}
            self.ui.info(
                f"Will create variant entry: '{word} - alt'\n"
                f"  Result: 2 separate entries (original + variant)"
            )
            return True

        return False

    def _display_existing_entry(self, word: str) -> None:
        """Display an existing vocabulary entry."""
        entry = self.vocab_repo.word_entries.get(word.lower())
        if not entry:
            self.ui.warning(f"Entry for '{word}' not found.")
            return

        defs = entry.get('definitions_list')
        exs = entry.get('examples_list')
        if not defs:
            defs = entry['definitions'].split('; ')
        if not exs:
            exs = []
            for e in entry['examples'].split('; '):
                if ' (' in e and e.endswith(')'):
                    fr, en = e.rsplit(' (', 1)
                    exs.append((fr, en[:-1]))

        self.ui.display_word_entry(entry['word'], [entry['type']], defs, exs)

    def _display_parsed_info(
        self,
        word: str,
        word_type: List[str],
        definitions: List[str],
        examples: List[Tuple[str, str]],
    ) -> None:
        """Display parsed word information."""
        word_type_str = ", ".join(word_type) if isinstance(word_type, list) else word_type
        self.ui.display_word_entry(word, word_type_str, definitions, examples)

    def _offer_sentence_routing(self, original_word: str, word_type: str) -> bool:
        """Offer to route sentence to translator. Returns True if routed."""
        title = self._translator_title(self.language_config.target_to_eng)
        route = self.ui.confirm(
            f"AI identified this as a sentence. Route to {title} instead?",
            default=True,
        )
        if not route:
            return False

        if not self.fr_to_eng_translator:
            alt_title = self._translator_title(self.language_config.target_to_eng)
            self.ui.error(
                f"{alt_title} is not available (initialization failed). "
                "Proceeding in vocab mode."
            )
            return False

        ok = self.fr_to_eng_translator.translate_and_save(original_word)
        if ok is False:
            self.ui.warning("Translation cancelled or failed.")
        else:
            self._show_post_translation_menu()
        return True

    def _translator_title(self, config: TranslatorConfig) -> str:
        """Get display title for a translator."""
        title = getattr(config, "ui_title", None)
        if title:
            return title
        source = getattr(config, "source_label", "Source")
        target = getattr(config, "target_label", "Target")
        return f"{source}  {target} Translator"

    def _show_post_translation_menu(self) -> None:
        """Show quick action menu after successful sentence translation."""
        # This is a simplified version - the full menu interaction
        # is handled by the caller when it detects sentence routing
        pass

    def _handle_merge(
        self,
        existing_word: str,
        new_type: str,
        new_defs: List[str],
        new_examples: List[Tuple[str, str]],
    ) -> bool:
        """Merge new definitions/examples into an existing entry."""
        return self.vocab_repo.merge_into_existing(
            existing_word, new_type, new_defs, new_examples
        )

    def _create_unique_variant(self, base_word: str) -> str:
        """Create a unique variant label for a duplicate word."""
        candidate = f"{base_word} - alt"
        if not self.vocab_repo.check_duplicate(candidate):
            return candidate
        # Try alphabetical suffixes
        for suffix in 'abcdefghijklmnopqrstuvwxyz':
            candidate = f"{base_word} - alt {suffix}"
            if not self.vocab_repo.check_duplicate(candidate):
                return candidate
        # Fallback with repeated 'alt'
        i = 2
        while True:
            candidate = f"{base_word} - alt x{i}"
            if not self.vocab_repo.check_duplicate(candidate):
                return candidate
            i += 1

    def _save_entry(
        self,
        *,
        insert_word: str,
        original_word: str,
        word_type: str,
        definitions: List[str],
        examples: List[Tuple[str, str]],
        latex_entry: str,
        history_action: str,
        history_existing_word: Optional[str],
        corrected_word_value: Optional[str],
    ) -> None:
        """Save the entry to repository and log to history."""
        if self._insert_entry_alphabetically_fn:
            self._insert_entry_alphabetically_fn(latex_entry, insert_word)
        else:
            self.vocab_repo.insert_entry_alphabetically(latex_entry, insert_word)

        if self._add_word_to_entries_fn:
            self._add_word_to_entries_fn(insert_word, word_type, definitions, examples)
        else:
            self.vocab_repo.add_word_to_entries(insert_word, word_type, definitions, examples)

        # Log to history
        if self.history_logger and self.history_logger.enabled:
            history_metadata: Dict[str, Any] = {}
            if history_existing_word:
                history_metadata["existing_word"] = history_existing_word
            if corrected_word_value:
                history_metadata["corrected_word"] = corrected_word_value
            if original_word != insert_word:
                history_metadata["original_input"] = original_word
                history_metadata["saved_word"] = insert_word
            if history_action == "force":
                history_metadata["forced_variant"] = insert_word

            try:
                self.history_logger.log_vocab_entry(
                    action=history_action,
                    word=insert_word,
                    word_type=word_type,
                    definitions=definitions,
                    examples=examples,
                    source_text=original_word,
                    normalized_key=self.vocab_repo.normalize_word(insert_word),
                    provider=self._provider_label_fn(),
                    latex_file=self.vocab_repo.latex_file,
                    metadata=history_metadata or None,
                )
            except Exception:
                pass  # Errors reported via logger's error handler

    def _show_quick_actions(self) -> bool:
        """Show quick action menu after successful entry. Returns True if flow continues."""
        try:
            quick_action = self.ui.interactive_menu(
                "What's next?",
                [
                    ("add", "Add another word"),
                    ("view", "View all vocabulary"),
                    ("search", "Search vocabulary"),
                    ("menu", "Return to main menu"),
                ],
                "Press Esc to return to main menu",
            )

            if quick_action == "add":
                # Signal to caller to run workflow again
                return True
            elif quick_action == "view":
                # Signal to caller to show vocabulary
                return True
            elif quick_action == "search":
                # Signal to caller to show search
                return True
            # "menu" - just return

        except KeyboardInterrupt:
            pass

        return True
