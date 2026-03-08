"""Word entry workflow orchestration.

This module handles the complete flow from user input to saved vocabulary entry,
including duplicate checking, AI querying, spelling correction, and persistence.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from vocab_builder.ai_response_parser import parse_ai_response_text
from vocab_builder.languages import LanguageConfig, TranslatorConfig
from vocab_builder.ui_helper import UIHelper, read_line

from .spelling_checker import SpellingChecker
from .history_logger import TranslationLogger
from .text_utils import detect_input_type, sanitize_user_text, translator_title

if TYPE_CHECKING:
    from .vocab_repository import VocabRepository
    from .llm_coordinator import LLMCoordinator
    from .translator import TranslatorCLI


@dataclass(frozen=True)
class _PreparedEntry:
    original_word: str
    detected_type: str
    ai_response: str
    final_word: str


@dataclass(frozen=True)
class _ParsedEntry:
    word_type: Any
    primary_word_type: str
    definitions: List[str]
    examples: List[Tuple[str, str]]


@dataclass(frozen=True)
class WorkflowOptions:
    max_word_length: int = 1000
    max_words: Optional[int] = None
    allow_sentence_punctuation: bool = True
    route_sentences: bool = True
    sentence_examples_in_vocab: bool = False
    entry_command: str = "\\entry"


@dataclass(frozen=True)
class WorkflowCallbacks:
    provider_label_fn: Callable[[], str] = field(default=lambda: "AI")
    on_settings: Optional[Callable[[], None]] = None
    on_entry_saved: Optional[Callable[[str], None]] = None
    on_post_translation_menu: Optional[Callable[[], Optional[str]]] = None
    get_word_input_fn: Optional[Callable[[], str]] = None
    query_ai_fn: Optional[Callable[[str], str]] = None
    check_spelling_fn: Optional[Callable[[str, str], Optional[str]]] = None
    parse_ai_response_fn: Optional[Callable[[str], Tuple[str, List[str], List[Tuple[str, str]]]]] = None
    check_duplicate_fn: Optional[Callable[[str], Optional[str]]] = None
    display_parsed_info_fn: Optional[Callable[[str, Any, List[str], List[Tuple[str, str]]], None]] = None
    display_latex_entry_fn: Optional[Callable[[str], None]] = None
    is_valid_latex_entry_fn: Optional[Callable[[str], bool]] = None
    insert_entry_alphabetically_fn: Optional[Callable[[str, str], bool]] = None
    add_word_to_entries_fn: Optional[Callable[[str, str, List[str], List[Tuple[str, str]]], None]] = None


class WorkflowOutcome(Enum):
    NO_SAVE = auto()
    SAVED = auto()
    ROUTED = auto()


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
        options: Optional[WorkflowOptions] = None,
        callbacks: Optional[WorkflowCallbacks] = None,
    ):
        self.vocab_repo = vocab_repo
        self.llm = llm
        self.ui = ui
        self.language_config = language_config
        self.history_logger = history_logger
        self.spelling_checker = spelling_checker or SpellingChecker(ui)
        self.fr_to_eng_translator = fr_to_eng_translator
        resolved_options = options or WorkflowOptions()
        resolved_callbacks = callbacks or WorkflowCallbacks()

        self.max_word_length = resolved_options.max_word_length
        self.max_words = resolved_options.max_words
        self.allow_sentence_punctuation = resolved_options.allow_sentence_punctuation
        self.route_sentences = resolved_options.route_sentences
        self.sentence_examples_in_vocab = resolved_options.sentence_examples_in_vocab
        self.entry_command = resolved_options.entry_command
        self._provider_label_fn = resolved_callbacks.provider_label_fn
        self._on_settings = resolved_callbacks.on_settings
        self._on_entry_saved = resolved_callbacks.on_entry_saved
        self._on_post_translation_menu = resolved_callbacks.on_post_translation_menu
        self._get_word_input_fn = resolved_callbacks.get_word_input_fn

        # Optional callbacks for tests and adapter layers.
        self._query_ai_fn = resolved_callbacks.query_ai_fn
        self._check_spelling_fn = resolved_callbacks.check_spelling_fn
        self._parse_ai_response_fn = resolved_callbacks.parse_ai_response_fn
        self._check_duplicate_fn = resolved_callbacks.check_duplicate_fn
        self._display_parsed_info_fn = resolved_callbacks.display_parsed_info_fn
        self._display_latex_entry_fn = resolved_callbacks.display_latex_entry_fn
        self._is_valid_latex_entry_fn = resolved_callbacks.is_valid_latex_entry_fn
        self._insert_entry_alphabetically_fn = resolved_callbacks.insert_entry_alphabetically_fn
        self._add_word_to_entries_fn = resolved_callbacks.add_word_to_entries_fn

        # Per-run state
        self.duplicate_resolution: Optional[Dict[str, str]] = None
        self.post_translation_action: Optional[str] = None

    def run(self, ensure_llm_ready_fn: Callable[[], bool]) -> WorkflowOutcome:
        """Execute the full word entry workflow.

        Args:
            ensure_llm_ready_fn: Function to check/initialize LLM. Returns True if ready.

        Returns:
            Workflow result describing whether an entry was saved, routed, or skipped.
        """
        self.post_translation_action = None
        prepared = self._prepare_entry(ensure_llm_ready_fn)
        if prepared is None:
            return WorkflowOutcome.NO_SAVE

        parsed = self._parse_entry(prepared.ai_response)
        if parsed is None:
            return WorkflowOutcome.NO_SAVE

        if self._maybe_route_sentence(prepared.original_word, parsed.word_type, parsed.primary_word_type):
            return WorkflowOutcome.ROUTED

        examples = self._maybe_drop_sentence_examples(parsed.primary_word_type, parsed.examples)
        self._display_parsed_entry(prepared.final_word, parsed.word_type, parsed.definitions, examples)

        merge_outcome = self._maybe_merge_and_finish(
            prepared.final_word,
            parsed.primary_word_type,
            parsed.definitions,
            examples,
        )
        if merge_outcome is not None:
            return merge_outcome

        if self._finalize_new_entry(prepared, parsed, examples):
            return WorkflowOutcome.SAVED
        return WorkflowOutcome.NO_SAVE

    def _prepare_entry(self, ensure_llm_ready_fn: Callable[[], bool]) -> Optional[_PreparedEntry]:
        if not self._ensure_llm_ready(ensure_llm_ready_fn):
            return None

        self.vocab_repo.ensure_entries_loaded()
        self.duplicate_resolution = None

        original_word = self._get_original_word()
        if not original_word:
            return None

        existing_word_check1 = self._check_duplicate(original_word)
        if existing_word_check1 and not self._handle_duplicate(original_word, existing_word_check1):
            self.ui.warning(f"Skipping '{original_word}' due to duplicate check (Stage 1).")
            return None

        detected_type = self._detect_input_type(original_word)
        self._maybe_show_sentence_hint(detected_type)

        ai_response = self._query_ai(original_word)
        if not ai_response:
            return None

        final_word = self._determine_final_word(original_word, ai_response, detected_type)
        if final_word is None:
            return None

        if not self._run_second_duplicate_check(final_word, original_word, existing_word_check1):
            return None

        return _PreparedEntry(
            original_word=original_word,
            detected_type=detected_type,
            ai_response=ai_response,
            final_word=final_word,
        )

    def _parse_entry(self, ai_response: str) -> Optional[_ParsedEntry]:
        word_type, definitions, examples, parsing_warnings = self._parse_ai_response(ai_response)
        if not self._report_parsing_status(definitions, examples, parsing_warnings):
            return None

        primary_word_type = self._primary_word_type(word_type)
        return _ParsedEntry(
            word_type=word_type,
            primary_word_type=primary_word_type,
            definitions=definitions,
            examples=examples,
        )

    def _maybe_drop_sentence_examples(
        self,
        primary_word_type: str,
        examples: List[Tuple[str, str]],
    ) -> List[Tuple[str, str]]:
        if primary_word_type.lower() == "sentence" and not self.sentence_examples_in_vocab:
            return []
        return examples

    def _finalize_new_entry(
        self,
        prepared: _PreparedEntry,
        parsed: _ParsedEntry,
        examples: List[Tuple[str, str]],
    ) -> bool:
        history_action, history_existing_word = self._resolve_history_context()

        insert_word = self._resolve_insert_word(prepared.final_word)
        latex_entry = self.vocab_repo.format_latex_entry(
            insert_word,
            parsed.primary_word_type,
            parsed.definitions,
            examples,
            entry_command=self.entry_command,
        )
        if not self._is_valid_latex_entry(latex_entry):
            self.ui.error("Cannot add vocabulary entry: Generated LaTeX is empty or invalid.")
            return False

        self._preview_latex_entry(latex_entry)

        corrected_word_value = prepared.final_word if prepared.final_word != prepared.original_word else None
        if not self._confirm_save(insert_word):
            self.duplicate_resolution = None
            return False

        if not self._save_entry(
            insert_word=insert_word,
            original_word=prepared.original_word,
            word_type=parsed.primary_word_type,
            definitions=parsed.definitions,
            examples=examples,
            latex_entry=latex_entry,
            history_action=history_action,
            history_existing_word=history_existing_word,
            corrected_word_value=corrected_word_value,
        ):
            self.duplicate_resolution = None
            return False

        self.duplicate_resolution = None

        entry_count = len(self.vocab_repo.word_entries)
        self.ui.success(f"Entry saved successfully! ({entry_count} entries total)")

        if self._on_entry_saved:
            self._on_entry_saved(insert_word)

        return True

    def _ensure_llm_ready(self, ensure_llm_ready_fn: Callable[[], bool]) -> bool:
        if ensure_llm_ready_fn():
            return True
        self.ui.info(
            "Returning to main menu without adding a word. "
            "Configure an AI provider to re-enable this flow."
        )
        return False

    def _get_original_word(self) -> str:
        if self._get_word_input_fn:
            return self._get_word_input_fn()
        return self._collect_input()

    def _check_duplicate(self, word: str) -> Optional[str]:
        if self._check_duplicate_fn:
            return self._check_duplicate_fn(word)
        return self.vocab_repo.check_duplicate(word)

    def _maybe_show_sentence_hint(self, detected_type: str) -> None:
        if detected_type != "sentence" or not self.route_sentences:
            return
        target_filename = self.language_config.target_to_eng.default_filename
        self.ui.info(
            "This looks like a sentence. After AI analysis, "
            f"you'll have the option to route it to {target_filename}.",
            accent="dim",
        )

    def _query_ai(self, original_word: str) -> Optional[str]:
        if self._query_ai_fn:
            return self._query_ai_fn(original_word)
        return self._query_ai_with_recovery(original_word)

    def _determine_final_word(self, original_word: str, ai_response: str, detected_type: str) -> Optional[str]:
        if detected_type == "sentence":
            return original_word

        if self._check_spelling_fn:
            final_word = self._check_spelling_fn(original_word, ai_response)
        else:
            final_word = self.spelling_checker.check(original_word, ai_response)

        if final_word is not None:
            return final_word

        preview = original_word.strip().replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        self.ui.warning(f"Abandoning entry for '{preview}'.")
        return None

    def _should_run_second_duplicate_check(self, final_word: str, original_word: str) -> bool:
        if final_word.lower() == original_word.lower():
            return False
        if self.duplicate_resolution and self.duplicate_resolution.get("mode") in ("merge", "force"):
            return False
        return True

    def _run_second_duplicate_check(
        self,
        final_word: str,
        original_word: str,
        existing_word_check1: Optional[str],
    ) -> bool:
        if not self._should_run_second_duplicate_check(final_word, original_word):
            return True

        existing_word_check2 = self._check_duplicate(final_word)
        if not existing_word_check2 or existing_word_check2 == existing_word_check1:
            return True

        self.ui.info(f"Performing second duplicate check for corrected word '{final_word}'...")
        if self._handle_duplicate(final_word, existing_word_check2):
            return True

        self.ui.warning(f"Skipping '{final_word}' due to duplicate check (Stage 2).")
        return False

    def _parse_ai_response(
        self, ai_response: str
    ) -> Tuple[Any, List[str], List[Tuple[str, str]], List[str]]:
        if self._parse_ai_response_fn:
            word_type, definitions, examples = self._parse_ai_response_fn(ai_response)
            return word_type, definitions, examples, []
        return self._parse_response(ai_response)

    def _report_parsing_status(
        self,
        definitions: List[str],
        examples: List[Tuple[str, str]],
        parsing_warnings: List[str],
    ) -> bool:
        if not definitions and not examples:
            self.ui.error(
                "Cannot add vocabulary entry: Failed to parse both definitions and examples from AI response."
            )
            for warning in parsing_warnings:
                self.ui.warning(warning)
            return False

        if not definitions:
            self.ui.warning("Could not parse definitions from AI response. Saving with examples only.")
        if not examples:
            self.ui.warning("Could not parse examples from AI response. Saving with definitions only.")
        for warning in parsing_warnings:
            if "Could not parse" not in warning:
                self.ui.info(warning, accent="dim")

        return True

    @staticmethod
    def _primary_word_type(word_type: Any) -> str:
        return word_type[0] if isinstance(word_type, list) else str(word_type or "")

    def _maybe_route_sentence(self, original_word: str, word_type: Any, primary_word_type: str) -> bool:
        if (
            isinstance(word_type, list)
            and primary_word_type.lower() == "sentence"
            and self.route_sentences
            and self._offer_sentence_routing(original_word, primary_word_type)
        ):
            return True
        return False

    def _display_parsed_entry(
        self,
        final_word: str,
        word_type: Any,
        definitions: List[str],
        examples: List[Tuple[str, str]],
    ) -> None:
        if self._display_parsed_info_fn:
            self._display_parsed_info_fn(final_word, word_type, definitions, examples)
        else:
            self._display_parsed_info(final_word, word_type, definitions, examples)

    def _maybe_merge_and_finish(
        self,
        final_word: str,
        primary_word_type: str,
        definitions: List[str],
        examples: List[Tuple[str, str]],
    ) -> Optional[WorkflowOutcome]:
        if not self.duplicate_resolution or self.duplicate_resolution.get("mode") != "merge":
            return None

        target_key = self.duplicate_resolution.get("existing", final_word)
        if self._handle_merge(target_key, primary_word_type, definitions, examples):
            self.ui.success(f"Merged AI content into existing entry for '{target_key}'.")
            self.duplicate_resolution = None
            return WorkflowOutcome.SAVED
        self.ui.warning(f"Merge for '{target_key}' failed. Nothing was saved.")
        self.duplicate_resolution = None
        return WorkflowOutcome.NO_SAVE

    def _resolve_history_context(self) -> Tuple[str, Optional[str]]:
        history_action = "new"
        history_existing_word: Optional[str] = None
        if self.duplicate_resolution:
            history_action = self.duplicate_resolution.get("mode", "new")
            history_existing_word = self.duplicate_resolution.get("existing")
        return history_action, history_existing_word

    def _resolve_insert_word(self, final_word: str) -> str:
        insert_word = final_word
        if self.duplicate_resolution and self.duplicate_resolution.get("mode") == "force":
            if self.vocab_repo.check_duplicate(insert_word):
                insert_word = self._create_unique_variant(insert_word)
        return insert_word

    def _is_valid_latex_entry(self, latex_entry: str) -> bool:
        if self._is_valid_latex_entry_fn:
            return self._is_valid_latex_entry_fn(latex_entry)
        return self.vocab_repo.is_valid_latex_entry(latex_entry)

    def _preview_latex_entry(self, latex_entry: str) -> None:
        if self._display_latex_entry_fn:
            self._display_latex_entry_fn(latex_entry)
        else:
            self.ui.display_latex_entry(latex_entry)

    def _confirm_save(self, insert_word: str) -> bool:
        if self.ui.confirm(
            f"Add this entry for '{insert_word}' to your vocabulary file?",
            default=True,
        ):
            return True
        self.ui.warning(f"Entry for '{insert_word}' discarded. Nothing saved.")
        return False

    def _collect_input(self) -> str:
        """Read target-language text from the user."""
        prompt = self._build_input_prompt()
        raw = self._read_user_input_line(prompt)
        if not raw:
            return ""
        if "\x1b" in raw:
            self.ui.warning("Input cancelled via Esc. Returning to main menu.")
            return ""

        word = self._sanitize_input(raw.strip())
        return self._validate_input(word)

    def _build_input_prompt(self) -> str:
        language_name = self.language_config.display_name
        limit_parts: list[str] = []
        if self.max_words:
            limit_parts.append(f"{self.max_words} words")
        if self.max_word_length:
            limit_parts.append(f"{self.max_word_length} chars")
        limit_hint = f" [{' '.join(limit_parts)}]" if limit_parts else ""
        return f"\nEnter {language_name} text{limit_hint} (Esc to cancel): "

    def _read_user_input_line(self, prompt: str) -> str:
        try:
            return read_line(prompt)
        except (EOFError, KeyboardInterrupt):
            self.ui.warning("Input cancelled. Returning to main menu.")
            return ""

    @staticmethod
    def _sanitize_input(word: str) -> str:
        return sanitize_user_text(word)

    def _validate_input(self, word: str) -> str:
        if not word:
            self.ui.error("Cannot add vocabulary entry: input cannot be empty.")
            return ""
        if self.max_words is not None and len(word.split()) > self.max_words:
            self.ui.error(f"Cannot add vocabulary entry: please limit to {self.max_words} words.")
            return ""
        if len(word) > self.max_word_length:
            self.ui.error(
                f"Cannot add vocabulary entry: please limit to {self.max_word_length} characters."
            )
            return ""
        if not self._is_valid_input(word):
            self.ui.error(
                "Cannot add vocabulary entry: input contains unsupported characters for "
                f"{self.language_config.display_name} text."
            )
            return ""
        return word

    def _is_valid_input(self, word: str) -> bool:
        """Validate user input using the active language configuration."""
        return self.language_config.input_validator(word, self.allow_sentence_punctuation)

    def _detect_input_type(self, text: str) -> str:
        return detect_input_type(text)

    def _query_ai_with_recovery(self, word: str) -> Optional[str]:
        """Query AI with recovery options on failure."""
        detected_type = self._detect_input_type(word)
        prompt_template = self.language_config.prompt_template
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

        self.ui.display_word_entry(entry['word'], entry['type'], defs, exs)

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
            return False

        self._show_post_translation_menu()
        return True

    def _translator_title(self, config: TranslatorConfig) -> str:
        """Get display title for a translator."""
        return translator_title(config)

    def _show_post_translation_menu(self) -> None:
        """Show quick actions after sentence routing."""
        if self._on_post_translation_menu:
            self.post_translation_action = self._on_post_translation_menu()

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
    ) -> bool:
        """Save the entry to repository and log to history."""
        if self._insert_entry_alphabetically_fn:
            written = self._insert_entry_alphabetically_fn(latex_entry, insert_word) is not False
        else:
            written = self.vocab_repo.insert_entry_alphabetically(latex_entry, insert_word)

        if not written:
            return False

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
            except Exception as exc:
                self.ui.warning(f"History logging failed: {exc}")
        return True
