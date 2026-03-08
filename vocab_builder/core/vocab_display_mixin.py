"""Vocabulary display and search helpers extracted from FrenchVocabBuilder."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from vocab_builder.ui_helper import read_line


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

    @staticmethod
    def _history_actions_for_additions() -> tuple[str, ...]:
        return ("new", "force")

    @staticmethod
    def _parse_history_timestamp(timestamp_str: str):
        from datetime import datetime, timezone

        try:
            timestamp = datetime.fromisoformat(timestamp_str)
        except (TypeError, ValueError):
            return None
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp

    def _resolve_existing_entry_key(self, word: str) -> Optional[str]:
        word_key = str(word or "").lower()
        if word_key in self.word_entries:
            return word_key

        normalized_entries = getattr(self, "normalized_entries", None)
        if isinstance(normalized_entries, dict):
            normalized_key = normalized_entries.get(self.normalize_word(word))
            if normalized_key in self.word_entries:
                return normalized_key

        normalized_target = self.normalize_word(word)
        for candidate in self.word_entries.keys():
            if self.normalize_word(candidate) == normalized_target:
                return candidate
        return None

    def _read_vocab_history(self, *, actions: Optional[tuple[str, ...]] = None) -> list[dict[str, Any]]:
        history_logger = getattr(self, "history_logger", None)
        if not history_logger:
            return []
        return history_logger.read_recent_vocab_entries(limit=None, actions=actions)

    def _collect_recent_additions(self, limit: int) -> list[tuple[str, dict[str, Any]]]:
        recent = self._read_vocab_history(actions=self._history_actions_for_additions())
        seen: set[str] = set()
        additions: list[tuple[str, dict[str, Any]]] = []

        for record in recent:
            entry_key = self._resolve_existing_entry_key(str(record.get("word", "")))
            if entry_key is None or entry_key in seen:
                continue
            seen.add(entry_key)
            additions.append((entry_key, record))
            if len(additions) >= limit:
                break

        return additions

    # --------------------------------------------------------------------- #
    # Browse submenu
    # --------------------------------------------------------------------- #

    def browse_vocabulary(self) -> None:
        """Open the vocabulary browsing submenu."""
        self._ensure_entries_loaded()

        while True:
            word_count = len(self.word_entries)
            options = [
                ("view_all", f"View all entries ({word_count})"),
                ("search", "Search vocabulary"),
                ("recent", "Recently added"),
                ("by_type", "Browse by word type"),
                ("flashcard", "Random flashcard"),
                ("stats", "Vocabulary stats"),
                ("back", "Back to main menu"),
            ]
            try:
                choice = self.ui.interactive_menu(
                    "Browse Vocabulary",
                    options,
                    "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
                )
            except KeyboardInterrupt:
                return

            if choice == "back":
                return

            handlers = {
                "view_all": self.display_all_vocabulary,
                "search": lambda: self.search_vocabulary(),
                "recent": self.show_recently_added,
                "by_type": self.browse_by_word_type,
                "flashcard": self.random_flashcard,
                "stats": self.show_vocab_stats,
            }
            handler = handlers.get(choice)
            if handler:
                handler()

    # --------------------------------------------------------------------- #
    # View all entries (existing)
    # --------------------------------------------------------------------- #

    def display_all_vocabulary(self):
        """Displays all vocabulary entries in a table."""
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

    # --------------------------------------------------------------------- #
    # Search
    # --------------------------------------------------------------------- #

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

    # --------------------------------------------------------------------- #
    # Recently added
    # --------------------------------------------------------------------- #

    @staticmethod
    def _format_relative_time(timestamp_str: str) -> str:
        from datetime import datetime, timezone

        try:
            ts = datetime.fromisoformat(timestamp_str)
            now = datetime.now(timezone.utc)
            delta = now - ts
            seconds = int(delta.total_seconds())
            if seconds < 60:
                return "just now"
            minutes = seconds // 60
            if minutes < 60:
                return f"{minutes}m ago"
            hours = minutes // 60
            if hours < 24:
                return f"{hours}h ago"
            days = hours // 24
            if days == 1:
                return "yesterday"
            if days < 30:
                return f"{days}d ago"
            return f"{days // 30}mo ago"
        except (ValueError, TypeError):
            return "unknown"

    def show_recently_added(self, limit: int = 15) -> None:
        """Display the most recently added vocabulary entries."""
        self._ensure_entries_loaded()
        if not getattr(self, "history_logger", None):
            self.ui.warning("History logging is not enabled.")
            return

        recent_additions = self._collect_recent_additions(limit)
        if not recent_additions:
            self.ui.info("No recent entries found in history.", accent="dim")
            return

        rows: list[list[str]] = []
        entry_keys: list[str] = []
        for entry_key, record in recent_additions:
            entry = self.word_entries[entry_key]
            action = str(record.get("action", "new"))
            action_label = "variant" if action == "force" else "added"
            rows.append([
                str(len(rows) + 1),
                entry["word"],
                self._format_entry_type(entry.get("type", record.get("word_type", ""))),
                action_label,
                self._format_relative_time(str(record.get("timestamp", ""))),
            ])
            entry_keys.append(entry_key)

        self.ui.render_table(
            title=f"Recently Added ({len(rows)} entries)",
            columns=["No.", "Word", "Type", "Action", "When"],
            rows=rows,
            column_styles=["cyan", "magenta", "green", "yellow", "dark_orange"],
        )

        # Offer detail view
        self.ui.info("View full entry by number; Enter to go back.", accent="dim")
        while True:
            choice_num = self._prompt_definition_number()
            if choice_num is None:
                return
            if choice_num < 0:
                continue
            if choice_num < 1 or choice_num > len(entry_keys):
                self.ui.warning("Please enter a valid entry number.")
                continue
            self.display_existing_entry(entry_keys[choice_num - 1])

    # --------------------------------------------------------------------- #
    # Browse by word type
    # --------------------------------------------------------------------- #

    def _collect_type_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.word_entries.values():
            entry_type = self._format_entry_type(entry.get("type", "unknown"))
            counts[entry_type] = counts.get(entry_type, 0) + 1
        return counts

    def browse_by_word_type(self) -> None:
        """Show entries filtered by word type."""
        self._ensure_entries_loaded()
        if not self.word_entries:
            self.ui.warning("No vocabulary entries found.")
            return

        type_counts = self._collect_type_counts()
        sorted_types = sorted(type_counts.items(), key=lambda x: (-x[1], x[0]))

        options = [
            (word_type, f"{word_type.capitalize()} ({count})")
            for word_type, count in sorted_types
        ]
        options.append(("back", "Back"))

        try:
            choice = self.ui.interactive_menu(
                "Browse by Word Type",
                options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            )
        except KeyboardInterrupt:
            return

        if choice == "back":
            return

        # Filter entries by selected type
        filtered: Dict[str, Dict] = {}
        for word_key, entry in self.word_entries.items():
            if self._format_entry_type(entry.get("type", "")) == choice:
                filtered[word_key] = entry

        if not filtered:
            self.ui.warning(f"No entries of type '{choice}' found.")
            return

        rows: list[list[str]] = []
        truncated: Dict[int, str] = {}
        for index, (_word, entry) in enumerate(
            sorted(filtered.items(), key=lambda x: self.normalize_word(x[0])), 1
        ):
            definitions = entry["definitions"]
            preview, was_truncated = self._preview_definition_text(definitions)
            if was_truncated:
                truncated[index] = definitions
            rows.append([
                str(index),
                entry["word"],
                preview,
            ])

        self.ui.render_table(
            title=f"{choice.capitalize()} ({len(filtered)} entries)",
            columns=["No.", "Word", "Definitions"],
            rows=rows,
            column_styles=["cyan", "magenta", "white"],
        )
        self._show_truncated_definitions(truncated)

    # --------------------------------------------------------------------- #
    # Random flashcard
    # --------------------------------------------------------------------- #

    def random_flashcard(self) -> None:
        """Show a random vocabulary entry as a flashcard."""
        import random

        self._ensure_entries_loaded()
        if not self.word_entries:
            self.ui.warning("No vocabulary entries available.")
            return

        keys = list(self.word_entries.keys())

        while True:
            word_key = random.choice(keys)
            entry = self.word_entries[word_key]
            word = entry["word"]

            self.ui.panel(
                f"[bold magenta]{word}[/bold magenta]",
                title="Flashcard",
                border_style="cyan",
            )

            try:
                read_line("Press Enter to reveal definition... ")
            except (EOFError, KeyboardInterrupt):
                return

            self.display_existing_entry(word_key)

            try:
                again = read_line("Another? (Enter = yes, Esc/n = done) ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            if again.lower() in ("n", "no") or "\x1b" in again:
                return

    # --------------------------------------------------------------------- #
    # Vocabulary stats
    # --------------------------------------------------------------------- #

    def show_vocab_stats(self) -> None:
        """Display a vocabulary statistics dashboard."""
        self._ensure_entries_loaded()
        total = len(self.word_entries)

        # Type breakdown
        type_counts = self._collect_type_counts()
        sorted_types = sorted(type_counts.items(), key=lambda x: (-x[1], x[0]))
        type_lines = "  ".join(
            f"[bold]{t.capitalize()}:[/bold] {c}" for t, c in sorted_types
        )

        # Recent activity from history
        last_added = ""
        week_count = 0
        recent_additions = self._read_vocab_history(actions=self._history_actions_for_additions())
        if recent_additions:
            last_record = recent_additions[0]
            last_timestamp = self._parse_history_timestamp(str(last_record.get("timestamp", "")))
            if last_timestamp is not None:
                last_word = last_record.get("word", "?")
                last_time = self._format_relative_time(str(last_record.get("timestamp", "")))
                last_added = f'"{last_word}" ({last_time})'

            from datetime import datetime, timezone, timedelta

            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            for record in recent_additions:
                timestamp = self._parse_history_timestamp(str(record.get("timestamp", "")))
                if timestamp is not None and timestamp >= cutoff:
                    week_count += 1

        lines: List[str] = [
            f"[bold]Total words:[/bold] {total}",
            "",
            f"[bold]By type:[/bold]  {type_lines}",
        ]
        if last_added:
            lines.append("")
            lines.append(f"[bold]Last added:[/bold] {last_added}")
            lines.append(f"[bold]This week:[/bold]  +{week_count} entries")

        language_name = getattr(self, "language_config", None)
        title = "Vocabulary Stats"
        if language_name:
            title = f"{language_name.display_name} Vocabulary Stats"

        self.ui.panel(
            "\n".join(lines),
            title=title,
            border_style="dark_orange",
        )
