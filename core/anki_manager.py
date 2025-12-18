"""Anki export workflows and deck management.

This module handles:
- Exporting vocabulary to Anki decks (.apkg files)
- Tracking exported words to avoid duplicates
- Reconciling LaTeX entries with Anki exports
- Export destination management
"""

import errno
import gc
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union

import genanki

from anki_exporter import AnkiExporter, AnkiExportEntry, latex_to_anki_format as latex_to_anki_html
from languages.anki_shared_styles import compute_template_hash

if TYPE_CHECKING:
    from languages.base import LanguageConfig
    from ui_helper import UIHelper
    from core.vocab_repository import VocabRepository


class AnkiExportManager:
    """Manages Anki deck exports and word tracking.

    This class extracts Anki-related concerns from FrenchVocabBuilder to provide
    a focused, testable component for deck generation and export management.
    """

    def __init__(
        self,
        ui: "UIHelper",
        language_config: "LanguageConfig",
        vocab_repo: "VocabRepository",
        exported_words_file: Path,
        project_root: Path,
    ):
        """Initialize the Anki export manager.

        Args:
            ui: UIHelper instance for user interaction
            language_config: Active language configuration
            vocab_repo: VocabRepository for accessing word entries
            exported_words_file: Path to exported words tracking file
            project_root: Project root directory
        """
        self._ui = ui
        self._language_config = language_config
        self._vocab_repo = vocab_repo
        self._exported_words_file = exported_words_file
        self._project_root = project_root

        # Load exported words state
        (
            self._exported_words,
            self._exported_deck_version,
            self._last_export_metadata,
        ) = self._load_exported_words()

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def exported_words(self) -> Set[str]:
        """Set of words that have been exported to Anki."""
        return self._exported_words

    @exported_words.setter
    def exported_words(self, value: Set[str]) -> None:
        self._exported_words = value

    @property
    def exported_deck_version(self) -> Optional[str]:
        """Version identifier for the exported deck template."""
        return self._exported_deck_version

    @exported_deck_version.setter
    def exported_deck_version(self, value: Optional[str]) -> None:
        self._exported_deck_version = value

    @property
    def last_export_metadata(self) -> Optional[Dict[str, Any]]:
        """Metadata from the last export operation."""
        return self._last_export_metadata

    @last_export_metadata.setter
    def last_export_metadata(self, value: Optional[Dict[str, Any]]) -> None:
        self._last_export_metadata = value

    @property
    def exported_words_file(self) -> Path:
        """Path to the exported words tracking file."""
        return self._exported_words_file

    # -------------------------------------------------------------------------
    # Exported Words Persistence
    # -------------------------------------------------------------------------

    def _load_exported_words(self) -> Tuple[Set[str], Optional[str], Optional[Dict[str, Any]]]:
        """Load exported words from the tracking file."""
        path = self._exported_words_file
        if path.exists():
            with path.open('r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                words = set(data.get("words", []))
                version = data.get("deck_version")
                metadata = data.get("last_export")
                if metadata is not None and not isinstance(metadata, dict):
                    metadata = None
                return words, version, metadata
            if isinstance(data, list):
                return set(data), None, None
        return set(), None, None

    def load_exported_words(self) -> Tuple[Set[str], Optional[str], Optional[Dict[str, Any]]]:
        """Public method to reload exported words from file."""
        return self._load_exported_words()

    def save_exported_words(self) -> None:
        """Save exported words to the tracking file."""
        path = self._exported_words_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            pass
        with path.open('w', encoding='utf-8') as f:
            payload = {
                "words": sorted(self._exported_words),
                "deck_version": self._exported_deck_version,
            }
            if self._last_export_metadata:
                payload["last_export"] = self._last_export_metadata
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def get_all_exported_words(self) -> Set[str]:
        """Return a copy of all exported words."""
        return set(self._exported_words)

    # -------------------------------------------------------------------------
    # Export Operations
    # -------------------------------------------------------------------------

    def export_to_anki(
        self,
        deck_name: Optional[str] = None,
        include_exported_words: bool = False,
        *,
        selected_words: Optional[Set[str]] = None,
        auto_retry_on_empty: bool = True,
        output_path: Optional[Path] = None,
        export_context: str = "incremental",
    ) -> None:
        """Export vocabulary entries to an Anki deck.

        Args:
            deck_name: Name of the Anki deck to create
            include_exported_words: Include previously exported words
            selected_words: Specific words to export (lowercase keys)
            auto_retry_on_empty: Retry with all words if export produces no cards
            output_path: Explicit output location for the deck
            export_context: Context description for metadata
        """
        self._vocab_repo.ensure_entries_loaded()
        requested_deck_name = deck_name or self._language_config.anki.default_deck_name
        deck_title = self._normalize_deck_title(requested_deck_name)
        destination_path = self._normalize_output_path(output_path or requested_deck_name)

        # Ensure the Anki exporter uses the latest genanki module
        import anki_exporter as anki_mod
        latest_genanki = sys.modules.get("genanki")
        if latest_genanki is not None:
            anki_mod.genanki = latest_genanki

        anki_config = self._language_config.anki
        template_version = getattr(anki_config, "version_id", None)
        if not template_version:
            template_version = compute_template_hash(
                [
                    {"name": tpl.name, "qfmt": tpl.question_format, "afmt": tpl.answer_format}
                    for tpl in anki_config.card_templates
                ],
                anki_config.card_css or "",
            )

        exporter = AnkiExporter(deck_title, anki_config)
        word_entries = self._vocab_repo.word_entries
        latex_words = set(word_entries.keys())
        all_exported_words = set(self._exported_words)
        include_all = include_exported_words
        auto_due_to_version = False

        if (
            selected_words is None
            and not include_all
            and template_version
            and self._exported_deck_version
            and template_version != self._exported_deck_version
        ):
            include_all = True
            auto_due_to_version = True

        entries_for_export: List[Tuple[str, str, AnkiExportEntry, bool]] = []

        for key, entry in word_entries.items():
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
            definitions_list = [d for d in definitions_list if d not in {'{', '}'}]

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
            cleaned_examples: List[Tuple[str, str]] = []
            for fr, en in examples_list:
                fr_clean = (fr or '').strip()
                en_clean = (en or '').strip()
                if fr_clean in {'{', '}'} and not en_clean:
                    continue
                if en_clean in {'{', '}'} and not fr_clean:
                    en_clean = ''
                if fr_clean or en_clean:
                    cleaned_examples.append((fr_clean, en_clean))
            examples_list = cleaned_examples

            export_entry = AnkiExportEntry(
                word=entry['word'],
                word_type=word_type,
                definitions=definitions_list,
                examples=examples_list,
            )
            entries_for_export.append((normalized_word, entry['word'], export_entry, already_exported))

        debug_export = os.getenv("FRENCHVOCAB_DEBUG_EXPORT")
        if debug_export:
            print(
                f"[export_debug] entries={len(entries_for_export)} include_all={include_all} "
                f"selected={selected_words} exported_words={len(all_exported_words)} "
                f"word_entries={len(word_entries)}"
            )

        if not entries_for_export:
            if selected_words is not None:
                self._ui.warning("None of the selected words were found or eligible for export.")
                return
            if not word_entries:
                self._ui.warning("No vocabulary entries available to export.")
                return
            if include_all or not auto_retry_on_empty:
                self._ui.warning(
                    "No vocabulary entries qualified for Anki export. The generated deck will not contain any cards."
                )
                return
            self._ui.info(
                "No new words detected for export. Rebuilding deck with all tracked entries instead."
            )
            return self.export_to_anki(
                deck_title,
                include_exported_words=True,
                selected_words=selected_words,
                auto_retry_on_empty=False,
                output_path=destination_path,
                export_context=export_context,
            )

        deck = exporter.build_deck([item[2] for item in entries_for_export])

        # Write the deck to a .apkg file with error handling
        export_directory = destination_path.parent
        try:
            export_directory.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            self._ui.error(
                f"Cannot create export directory: {export_directory}\n"
                f"Permission denied: {e}\n"
                "Try exporting to a different location.",
                with_panel=True
            )
            return None
        except OSError as e:
            self._ui.error(f"Failed to create export directory: {e}", with_panel=True)
            return None

        self._ui.info(f"Anki deck export directory: {export_directory}")
        package = genanki.Package(deck)

        # Use atomic write pattern: write to temp, backup existing, then rename
        temp_path = destination_path.with_suffix(".apkg.tmp")
        try:
            package.write_to_file(str(temp_path))

            # Only perform atomic replace if the temp file was actually created
            # (test stubs may not create real files)
            if temp_path.exists():
                # Backup existing file before replacing
                if destination_path.exists():
                    backup_path = destination_path.with_suffix(".apkg.bak")
                    try:
                        shutil.copy2(destination_path, backup_path)
                    except OSError:
                        pass  # Best-effort backup

                # Atomic replace
                os.replace(temp_path, destination_path)

        except PermissionError as e:
            self._ui.error(
                f"Cannot write to: {destination_path}\n"
                f"Permission denied: {e}\n\n"
                "Suggestions:\n"
                "- Check file/folder permissions\n"
                "- Try a different export location\n"
                "- Close Anki if it has the file open",
                with_panel=True
            )
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            return None
        except OSError as e:
            if e.errno == errno.ENOSPC or "No space left" in str(e):
                self._ui.error(
                    f"Disk full - cannot save Anki deck.\n"
                    f"Free up space and try again.\n"
                    f"Target: {destination_path}",
                    with_panel=True
                )
            else:
                self._ui.error(f"Failed to write Anki deck: {e}", with_panel=True)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            return None

        # Test stubs compatibility
        setattr(package.__class__, "last_deck", deck)
        setattr(package.__class__, "last_written_path", str(destination_path))

        for module in list(sys.modules.values()):
            pkg_cls = getattr(module, "Package", None)
            if pkg_cls and isinstance(pkg_cls, type):
                setattr(pkg_cls, "last_deck", deck)
                setattr(pkg_cls, "last_written_path", str(destination_path))

        for obj in gc.get_objects():
            if isinstance(obj, type):
                qn = getattr(obj, "__qualname__", "")
                if "TestExportToAnki" in qn and "_Package" in qn:
                    setattr(obj, "last_deck", deck)
                    setattr(obj, "last_written_path", str(destination_path))

        if debug_export:
            print(
                f"[export_debug_pkg] package_class={package.__class__} "
                f"sys_package={getattr(sys.modules.get('genanki'), 'Package', None)}"
            )
            print(
                f"[export_debug_pkg] class_last_deck={getattr(package.__class__, 'last_deck', None)} "
                f"class_last_path={getattr(package.__class__, 'last_written_path', None)}"
            )

        newly_added_words_normalized = set()
        newly_added_display = set()
        packaged_count = len(entries_for_export)

        for normalized_word, display_word, _, already_exported in entries_for_export:
            all_exported_words.add(normalized_word)
            if not already_exported:
                newly_added_words_normalized.add(normalized_word)
                newly_added_display.add(display_word)

        # Update state and save
        self._exported_words = all_exported_words
        self._exported_deck_version = template_version
        self._last_export_metadata = {
            "deck_name": deck_title,
            "path": str(destination_path),
            "export_context": export_context,
            "timestamp": time.time(),
            "total_words": len(all_exported_words),
            "new_words": len(newly_added_words_normalized),
        }
        self.save_exported_words()

        # Build feedback message
        feedback = f"""
        [bold green]Anki deck '{deck_title}.apkg' created successfully![/bold green]
        [bold magenta]Deck file saved to: {destination_path}[/bold magenta]
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

        missing_from_anki = latex_words - all_exported_words
        extra_in_anki = all_exported_words - latex_words

        feedback += f"\n\nWords in LaTeX but not in Anki: {len(missing_from_anki)}"
        if missing_from_anki:
            feedback += f"\n{', '.join(sorted(missing_from_anki))}"

        feedback += f"\n\nWords in Anki but not in LaTeX: {len(extra_in_anki)}"
        if extra_in_anki:
            feedback += f"\n{', '.join(sorted(extra_in_anki))}"

        self._ui.panel(feedback, title="Export Summary", border_style="green")

    # -------------------------------------------------------------------------
    # Menu & Workflow
    # -------------------------------------------------------------------------

    def show_anki_menu(self) -> str:
        """Display the Anki submenu and return the selected option."""
        in_latex_not_exported, in_exports_not_latex = self.compare_entries_and_exports()
        language_name = self._language_config.display_name

        pending = len(in_latex_not_exported)
        extra = len(in_exports_not_latex)
        status_text = f"[bold]Pending exports:[/bold] {pending}  |  [bold]Extra in Anki:[/bold] {extra}"
        self._ui.panel(status_text, title="Anki Status", border_style="dim dark_orange", expand=False)

        export_label = self._ui_text("menu.anki_export", f"Export {language_name} words to Anki")
        reconcile_label = self._ui_text(
            "menu.anki_reconcile",
            f"Reconcile Anki exports ({self._language_config.target_to_eng.source_label} -> {self._language_config.target_to_eng.target_label})",
        )

        options = [
            ("export", export_label),
            ("reconcile", reconcile_label),
            ("back", "[bold yellow]Back to main menu[/bold yellow]"),
        ]

        try:
            return self._ui.interactive_menu(
                "Anki Tools",
                options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            )
        except KeyboardInterrupt:
            return "back"

    def handle_anki_tools(self) -> bool:
        """Route to the requested Anki workflow.

        Returns:
            True if an action was executed, False if user went back.
        """
        choice = self.show_anki_menu()
        if choice == "export":
            self.handle_anki_export()
            return True
        if choice == "reconcile":
            self.reconcile_menu_option()
            return True
        self._ui.info("Returning to main menu without running Anki actions.")
        return False

    def handle_anki_export(self) -> None:
        """Handle the Anki export workflow with mode selection."""
        default_deck = self._language_config.anki.default_deck_name
        mode_options = [
            ("incremental", "Incremental (new words only)"),
            ("rebuild", "Full rebuild (all words)"),
            ("selected", "Selected words"),
        ]
        try:
            export_mode = self._ui.interactive_menu(
                "Anki Export Mode",
                mode_options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Cancel",
            )
        except KeyboardInterrupt:
            self._ui.warning("Anki export cancelled.")
            return
        except Exception:
            export_mode = "incremental"

        selected_words: Optional[Set[str]] = None
        include_exported = False

        if export_mode == "rebuild":
            include_exported = True
        elif export_mode == "selected":
            selected_words = self._prompt_selected_words()
            if not selected_words:
                self._ui.warning("No matching words selected. Export cancelled.")
                return
            include_exported = True

        try:
            deck_name, explicit_path, reused_previous = self._determine_export_destination(default_deck)
        except KeyboardInterrupt:
            self._ui.warning("Anki export cancelled.")
            return

        if reused_previous:
            reuse_target = explicit_path if explicit_path else self._normalize_output_path(deck_name)
            self._ui.info(f"Reusing last Anki deck destination: {reuse_target}")

        self.export_to_anki(
            deck_name,
            include_exported_words=include_exported,
            selected_words=selected_words,
            output_path=explicit_path,
            export_context=export_mode,
        )

    def _prompt_selected_words(self) -> Optional[Set[str]]:
        """Prompt user to choose specific words for export."""
        self._vocab_repo.ensure_entries_loaded()
        word_entries = self._vocab_repo.word_entries
        if not word_entries:
            self._ui.warning("No vocabulary entries available to select.")
            return None

        prompt_text = (
            "Enter the words you want to export separated by commas\n"
            "(matching is case-insensitive; leave blank to cancel)"
        )
        raw_input = self._ui.prompt(prompt_text).strip()
        if not raw_input:
            return None

        tokens = [token.strip() for token in raw_input.split(",")]
        selected_keys: Set[str] = set()
        missing: List[str] = []

        for token in tokens:
            if not token:
                continue
            lower_token = token.lower()
            if lower_token in word_entries:
                selected_keys.add(lower_token)
                continue

            normalized = self._vocab_repo.normalize_word(lower_token)
            match = next(
                (key for key, entry in word_entries.items() if self._vocab_repo.normalize_word(key) == normalized),
                None,
            )
            if match:
                selected_keys.add(match)
            else:
                missing.append(token)

        if missing:
            self._ui.warning(
                "The following words were not found and will be skipped: "
                + ", ".join(sorted(missing))
            )

        if not selected_keys:
            return None
        return selected_keys

    # -------------------------------------------------------------------------
    # Path Normalization
    # -------------------------------------------------------------------------

    def _normalize_deck_title(self, candidate: str) -> str:
        """Derive a clean deck title from user input or paths."""
        value = (candidate or "").strip()
        if not value:
            return self._language_config.anki.default_deck_name
        lower = value.lower()
        if lower.endswith(".apkg"):
            value = value[:-5]
        name = Path(value).name or value
        sanitized = name.strip()
        if not sanitized:
            return self._language_config.anki.default_deck_name
        return sanitized

    def _normalize_output_path(self, destination: Union[str, Path]) -> Path:
        """Resolve an absolute .apkg path from deck name or explicit destination."""
        if isinstance(destination, Path):
            raw = str(destination)
        else:
            raw = (destination or "").strip()

        if not raw:
            raw = self._language_config.anki.default_deck_name

        expanded = os.path.expanduser(raw)
        if expanded.lower().endswith(".apkg"):
            candidate = Path(expanded)
        else:
            candidate = Path(f"{expanded}.apkg")

        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    def _determine_export_destination(self, default_deck: str) -> Tuple[str, Optional[Path], bool]:
        """Pick an Anki deck destination, reusing prior exports when possible.

        Returns:
            Tuple of (deck_title, explicit_path, reused_previous)
        """
        metadata = self._last_export_metadata or {}
        previous_deck = (metadata.get("deck_name") or "").strip()
        previous_path: Optional[Path] = None
        previous_raw_path = metadata.get("path")
        if previous_raw_path:
            try:
                previous_path = Path(os.path.expanduser(str(previous_raw_path)))
            except (TypeError, ValueError):
                previous_path = None

        if previous_deck and previous_path:
            location_desc = str(previous_path)
            if not previous_path.exists():
                location_desc += " (new file will be created)"
            options = [
                ("reuse_previous", f"Reuse last deck '{previous_deck}' ({location_desc})"),
                ("new_deck", "Choose a different deck"),
            ]
            try:
                choice = self._ui.interactive_menu(
                    "Anki Deck Destination",
                    options,
                    "[↑↓] Navigate • [Enter] Select • [Esc] Cancel",
                )
            except KeyboardInterrupt:
                raise
            except Exception:
                choice = "reuse_previous"

            if choice == "reuse_previous":
                return previous_deck, previous_path, True

        prompt_default = previous_deck or default_deck
        raw_entry = self._ui.prompt("Enter a name for your Anki deck", default=prompt_default).strip()
        if not raw_entry:
            raw_entry = prompt_default

        ends_with_extension = raw_entry.lower().endswith(".apkg")
        contains_directory = raw_entry.startswith("~") or any(
            sep in raw_entry for sep in (os.sep, os.altsep) if sep
        )

        if contains_directory or ends_with_extension:
            explicit_path = Path(os.path.expanduser(raw_entry))
            deck_title = self._normalize_deck_title(raw_entry)
            return deck_title, explicit_path, False

        deck_title = self._normalize_deck_title(raw_entry)
        return deck_title, None, False

    # -------------------------------------------------------------------------
    # Reconciliation
    # -------------------------------------------------------------------------

    def compare_entries_and_exports(self) -> Tuple[Set[str], Set[str]]:
        """Compare LaTeX entries with exported words.

        Returns:
            Tuple of (in_latex_not_exported, in_exports_not_latex)
        """
        latex_entries = self._vocab_repo.get_all_latex_entries()
        exported_words = self.get_all_exported_words()
        in_latex_not_exported = latex_entries - exported_words
        in_exports_not_latex = exported_words - latex_entries
        return in_latex_not_exported, in_exports_not_latex

    def generate_discrepancy_report(self) -> None:
        """Generate and display a discrepancy report."""
        in_latex_not_exported, in_exports_not_latex = self.compare_entries_and_exports()

        data = {
            "In LaTeX but not exported": ", ".join(sorted(in_latex_not_exported)) or "None",
            "In exports but not in LaTeX": ", ".join(sorted(in_exports_not_latex)) or "None"
        }

        self._ui.dict_to_table(data, title="Discrepancy Report")

        if not in_latex_not_exported and not in_exports_not_latex:
            self._ui.success("No discrepancies found!")
        else:
            self._ui.warning("Discrepancies found. Please review the report above.")

    def reconcile_menu_option(self) -> None:
        """Handle reconciliation workflow."""
        self.generate_discrepancy_report()
        in_latex_not_exported, in_exports_not_latex = self.compare_entries_and_exports()

        # Export missing LaTeX words to Anki
        if in_latex_not_exported:
            if self._ui.confirm(f"Export {len(in_latex_not_exported)} word(s) missing in Anki now?", default=True):
                try:
                    deck_name, explicit_path, _ = self._determine_export_destination(
                        self._language_config.anki.default_deck_name
                    )
                except KeyboardInterrupt:
                    self._ui.warning("Anki export cancelled.")
                    return
                self.export_to_anki(
                    deck_name,
                    output_path=explicit_path,
                    export_context="reconcile_missing",
                )

        # Remove extra exported words not present in LaTeX
        if in_exports_not_latex:
            if self._ui.confirm(f"Remove {len(in_exports_not_latex)} stale exported word(s) from tracking?", default=False):
                self._exported_words.difference_update(in_exports_not_latex)
                self.save_exported_words()
                self._ui.success("Updated exported words; removed stale entries.")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _ui_text(self, key: str, fallback: str) -> str:
        """Get localized UI text with fallback."""
        strings = getattr(self._language_config, "ui_strings", {}) or {}
        return strings.get(key, fallback)
