"""Vocabulary display and search helpers extracted from FrenchVocabBuilder."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ui_helper import read_line


class VocabDisplayMixin:
    @staticmethod
    def _format_entry_type(entry_type: Any) -> str:
        if isinstance(entry_type, str):
            return entry_type
        if isinstance(entry_type, list):
            return ", ".join(entry_type)
        return str(entry_type)

    def _preview_definition_text(self, definitions: str) -> tuple[str, bool]:
        if len(definitions) <= self.DEFINITION_PREVIEW_LIMIT:
            return definitions, False
        return definitions[: self.DEFINITION_PREVIEW_LIMIT - 3] + "...", True

    def _build_all_vocab_table_rows(self) -> tuple[list[list[str]], Dict[int, str]]:
        sorted_entries = sorted(self.word_entries.items(), key=lambda x: self.normalize_word(x[0]))
        rows: list[list[str]] = []
        truncated_definitions: Dict[int, str] = {}

        for index, (_word, entry) in enumerate(sorted_entries, 1):
            definitions = entry["definitions"]
            preview, was_truncated = self._preview_definition_text(definitions)
            if was_truncated:
                truncated_definitions[index] = definitions

            rows.append(
                [
                    str(index),
                    entry["word"],
                    self._format_entry_type(entry["type"]),
                    preview,
                ]
            )

        return rows, truncated_definitions

    def _prompt_definition_number(self) -> Optional[int]:
        try:
            choice = read_line("Show full definitions for # (Enter/Esc to finish): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if "\x1b" in choice:
            return None
        if not choice or choice == "0":
            return None
        if not choice.isdigit():
            self.ui.warning("Enter a number or press Enter to finish.")
            return -1
        return int(choice)

    def _show_truncated_definitions(self, truncated_definitions: Dict[int, str]) -> None:
        if not truncated_definitions:
            return

        self.ui.info(
            "Some definitions are abbreviated. View any by number; Enter to continue.",
            accent="dim",
        )

        while True:
            entry_number = self._prompt_definition_number()
            if entry_number is None:
                return
            if entry_number < 0:
                continue

            full_text = truncated_definitions.get(entry_number)
            if full_text is None:
                self.ui.warning("Please enter a valid entry number.")
                continue

            self.ui.panel(
                full_text,
                title=f"Definitions for entry {entry_number}",
                border_style="dark_orange",
                expand=True,
            )

    def _prompt_optional_search_query(self) -> str:
        return self.ui.prompt("Search vocabulary (press Enter to skip)", style="dim").strip()

    def display_all_vocabulary(self):
        """Displays all vocabulary entries present in the LaTeX file in a paginated table format.

        This function retrieves all vocabulary entries from the LaTeX file, formats them
        into a Rich table, and displays them with pagination for better readability.
        """
        self._ensure_entries_loaded()
        if not self.word_entries:
            self.ui.warning("No vocabulary entries found in the LaTeX file.")
            return

        headers = ["No.", "Word", "Type", "Definitions"]
        rows, truncated_definitions = self._build_all_vocab_table_rows()
        self.ui.render_table(
            title=f"All Vocabulary Entries ({len(self.word_entries)} words)",
            columns=headers,
            rows=rows,
            column_styles=["cyan", "magenta", "green", "white"],
        )

        self._show_truncated_definitions(truncated_definitions)

        search_query = self._prompt_optional_search_query()
        if search_query:
            self.search_vocabulary(search_query)

    def _resolve_search_term(self, search_term: Optional[str]) -> str:
        if search_term is None:
            search_term = self.ui.prompt("Enter search term").strip()
        return search_term.strip().lower()

    @staticmethod
    def _entry_matches_search_term(search_term: str, word_key: str, entry: Dict[str, Any]) -> bool:
        if search_term in word_key.lower():
            return True
        if search_term in str(entry.get("definitions", "")).lower():
            return True

        entry_type = entry.get("type", "")
        if isinstance(entry_type, str):
            return search_term in entry_type.lower()
        if isinstance(entry_type, list):
            for t in entry_type:
                if search_term in str(t).lower():
                    return True
        return False

    def _collect_search_results(self, search_term: str) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        for word, entry in self.word_entries.items():
            if self._entry_matches_search_term(search_term, word, entry):
                results[word] = entry
        return results

    def _build_search_results_rows(self, results: Dict[str, Any]) -> list[list[str]]:
        rows: list[list[str]] = []
        for _word, entry in sorted(results.items(), key=lambda x: self.normalize_word(x[0])):
            preview, _ = self._preview_definition_text(entry["definitions"])
            rows.append(
                [
                    entry["word"],
                    self._format_entry_type(entry["type"]),
                    preview,
                ]
            )
        return rows

    def _maybe_view_full_entry_from_results(self) -> None:
        if not self.ui.confirm(
            "Would you like to see the full entry for any of these words?",
            default=False,
        ):
            return

        word_to_view = self.ui.prompt("Enter the word to view").strip()
        if not word_to_view:
            return

        word_key = word_to_view.lower()
        if word_key in self.word_entries:
            self.display_existing_entry(word_key)
            return

        normalized_target = self.normalize_word(word_to_view)
        for candidate in self.word_entries.keys():
            if self.normalize_word(candidate) == normalized_target:
                self.display_existing_entry(candidate)
                return

        self.ui.error(f"Word '{word_to_view}' not found.")

    def search_vocabulary(self, search_term: Optional[str] = None):
        """Allows searching for specific vocabulary entries by keyword."""
        self._ensure_entries_loaded()
        search_term = self._resolve_search_term(search_term)
        if not search_term:
            self.ui.info("Search skipped.", accent="dim")
            return

        results = self._collect_search_results(search_term)
        if not results:
            self.ui.warning(f"No results found for '{search_term}'.")
            return

        headers = ["Word", "Type", "Definitions"]
        rows = self._build_search_results_rows(results)
        self.ui.render_table(
            title=f"Search Results for '{search_term}' ({len(results)} matches)",
            columns=headers,
            rows=rows,
            column_styles=["magenta", "green", "white"],
        )

        self._maybe_view_full_entry_from_results()

