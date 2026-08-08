"""Anki export workflows and deck management.

This module handles:
- Exporting vocabulary to Anki decks (.apkg files)
- Tracking exported words to avoid duplicates
- Reconciling LaTeX entries with Anki exports
- Export destination management
"""

import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from vocab_builder.anki_exporter import (
    AnkiExporter,
    AnkiExportEntry,
    AnkiMistakeDeckExporter,
    AnkiMistakeEntry,
)
from vocab_builder.compat import get_env
from vocab_builder.core.file_safety import atomic_write_text, create_backup_snapshot, file_lock
from vocab_builder.core.history_logger import default_history_base_dir
from vocab_builder.languages.anki_shared_styles import compute_template_hash

if TYPE_CHECKING:
    from vocab_builder.languages.base import LanguageConfig
    from vocab_builder.ui_helper import UIHelper
    from vocab_builder.core.vocab_repository import VocabRepository


class AnkiSnapshotStatus(str, Enum):
    """Outcome of a non-interactive snapshot check."""

    EXPORTED = "exported"
    UNCHANGED = "unchanged"
    NO_ENTRIES = "no_entries"
    FAILED = "failed"


@dataclass(frozen=True)
class AnkiSnapshotResult:
    """Result returned by the clean-exit snapshot workflow."""

    status: AnkiSnapshotStatus
    path: Optional[Path] = None
    packaged_count: int = 0


def exit_snapshot_enabled(default: bool = True) -> bool:
    """Return whether clean-exit Anki snapshots are enabled."""
    value = get_env("VOCABBUILDER_EXIT_SNAPSHOT")
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


class AnkiExportManager:
    """Manages Anki deck exports and word tracking.

    This class extracts Anki-related concerns from VocabBuilder to provide
    a focused, testable component for deck generation and export management.
    """

    EXPORT_DIRECTORY_NAME = "anki_exports"

    def __init__(
        self,
        ui: "UIHelper",
        language_config: "LanguageConfig",
        vocab_repo: "VocabRepository",
        exported_words_file: Path,
        project_root: Path,
        composition_history_paths: Optional[Sequence[Path]] = None,
        entry_history_reader: Optional[Callable[[], Sequence[Dict[str, Any]]]] = None,
    ):
        """Initialize the Anki export manager.

        Args:
            ui: UIHelper instance for user interaction
            language_config: Active language configuration
            vocab_repo: VocabRepository for accessing word entries
            exported_words_file: Path to exported words tracking file
            project_root: Project root directory
            entry_history_reader: Optional reader used to recover acquisition order
        """
        self._ui = ui
        self._language_config = language_config
        self._vocab_repo = vocab_repo
        project_root_path = Path(project_root).expanduser()
        if not project_root_path.is_absolute():
            project_root_path = Path.cwd() / project_root_path
        self._project_root = project_root_path.absolute()
        exported_words_path = Path(exported_words_file).expanduser()
        if not exported_words_path.is_absolute():
            exported_words_path = self._project_root / exported_words_path
        self._exported_words_file = exported_words_path.absolute()
        self._default_export_directory = self._resolve_default_export_directory()
        self._composition_history_paths = self._resolve_composition_history_paths(
            composition_history_paths
        )
        self._entry_history_reader = entry_history_reader
        self._entry_order: List[str] = []
        self._snapshot_hash: Optional[str] = None
        self._snapshot_export_metadata: Optional[Dict[str, Any]] = None

        # Load exported words state
        (
            self._exported_words,
            self._exported_deck_version,
            self._last_export_metadata,
        ) = self._load_exported_words()
        self._remember_persisted_export_state()

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
    def entry_order(self) -> Tuple[str, ...]:
        """Stable, non-alphabetical order used when packaging Anki notes."""
        return tuple(self._entry_order)

    @property
    def snapshot_hash(self) -> Optional[str]:
        """Hash of the most recent complete vocabulary package."""
        return self._snapshot_hash

    @property
    def snapshot_export_metadata(self) -> Optional[Dict[str, Any]]:
        """Destination metadata for the most recent complete package."""
        if self._snapshot_export_metadata is None:
            return None
        return dict(self._snapshot_export_metadata)

    @property
    def exported_words_file(self) -> Path:
        """Path to the exported words tracking file."""
        return self._exported_words_file

    # -------------------------------------------------------------------------
    # Exported Words Persistence
    # -------------------------------------------------------------------------

    def _load_exported_words(self) -> Tuple[Set[str], Optional[str], Optional[Dict[str, Any]]]:
        """Load exported words from the tracking file."""
        self._entry_order = []
        self._snapshot_hash = None
        self._snapshot_export_metadata = None
        path = self._exported_words_file
        if path.exists():
            try:
                with path.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
                self._preserve_invalid_export_state(path, exc)
                return set(), None, None
            if isinstance(data, dict):
                return self._parse_exported_words_dict(data, path)
            if isinstance(data, list):
                return self._parse_legacy_exported_words_list(data, path)
            self._preserve_invalid_export_state(path, "unexpected JSON payload type")
        return set(), None, None

    def load_exported_words(self) -> Tuple[Set[str], Optional[str], Optional[Dict[str, Any]]]:
        """Public method to reload exported words from file."""
        return self._load_exported_words()

    def save_exported_words(self) -> bool:
        """Merge and atomically save export state under the catalog lock."""
        path = self._exported_words_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._ui.error(f"Failed to prepare exported words directory: {exc}", with_panel=True)
            return False
        with file_lock(path):
            local_state = self._capture_export_state()
            current_state = self._read_export_state()
            base_state = getattr(self, "_persisted_export_state", local_state)
            merged_state = self._merge_export_states(
                base=base_state,
                current=current_state,
                local=local_state,
            )
            self._apply_export_state(merged_state)
            payload = self._export_state_payload()
            content = json.dumps(payload, ensure_ascii=False, indent=2)
            try:
                atomic_write_text(path, content, create_backup=True)
            except OSError as exc:
                self._apply_export_state(local_state)
                self._ui.error(
                    f"Failed to save exported words state atomically: {exc}\n"
                    f"Tracker path: {path}",
                    with_panel=True,
                )
                return False
            self._remember_persisted_export_state()
            return True

    def _read_export_state(self) -> Dict[str, Any]:
        local_state = self._capture_export_state()
        words, deck_version, last_export = self._load_exported_words()
        current_state = {
            "words": set(words),
            "deck_version": deck_version,
            "entry_order": list(self._entry_order),
            "snapshot_hash": self._snapshot_hash,
            "snapshot_export": (
                dict(self._snapshot_export_metadata)
                if self._snapshot_export_metadata is not None
                else None
            ),
            "last_export": dict(last_export) if last_export is not None else None,
        }
        self._apply_export_state(local_state)
        return current_state

    def _merge_current_export_state(self) -> None:
        local_state = self._capture_export_state()
        current_state = self._read_export_state()
        base_state = getattr(self, "_persisted_export_state", local_state)
        self._apply_export_state(
            self._merge_export_states(
                base=base_state,
                current=current_state,
                local=local_state,
            )
        )

    def _capture_export_state(self) -> Dict[str, Any]:
        return {
            "words": set(self._exported_words),
            "deck_version": self._exported_deck_version,
            "entry_order": list(self._entry_order),
            "snapshot_hash": self._snapshot_hash,
            "snapshot_export": (
                dict(self._snapshot_export_metadata)
                if self._snapshot_export_metadata is not None
                else None
            ),
            "last_export": (
                dict(self._last_export_metadata)
                if self._last_export_metadata is not None
                else None
            ),
        }

    def _apply_export_state(self, state: Dict[str, Any]) -> None:
        self._exported_words = set(state["words"])
        self._exported_deck_version = state.get("deck_version")
        self._entry_order = list(state.get("entry_order") or [])
        self._snapshot_hash = state.get("snapshot_hash")
        snapshot_export = state.get("snapshot_export")
        self._snapshot_export_metadata = dict(snapshot_export) if snapshot_export else None
        last_export = state.get("last_export")
        self._last_export_metadata = dict(last_export) if last_export else None

    def _remember_persisted_export_state(self) -> None:
        self._persisted_export_state = self._capture_export_state()

    @staticmethod
    def _merge_export_states(
        *,
        base: Dict[str, Any],
        current: Dict[str, Any],
        local: Dict[str, Any],
    ) -> Dict[str, Any]:
        base_words = set(base["words"])
        local_words = set(local["words"])
        merged_words = (
            set(current["words"])
            | (local_words - base_words)
        ) - (base_words - local_words)

        base_order = list(base.get("entry_order") or [])
        local_order = list(local.get("entry_order") or [])
        removed_order = set(base_order) - set(local_order)
        merged_order = [
            key for key in current.get("entry_order") or []
            if key not in removed_order
        ]
        merged_order.extend(key for key in local_order if key not in merged_order)

        merged: Dict[str, Any] = {
            "words": merged_words,
            "entry_order": merged_order,
        }
        for key in ("deck_version", "snapshot_hash", "snapshot_export", "last_export"):
            merged[key] = local.get(key) if local.get(key) != base.get(key) else current.get(key)
        return merged

    def _export_state_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "words": sorted(self._exported_words),
            "deck_version": self._exported_deck_version,
            "entry_order": list(self._entry_order),
        }
        if self._snapshot_hash:
            payload["snapshot_hash"] = self._snapshot_hash
        if self._snapshot_export_metadata:
            payload["snapshot_export"] = self._snapshot_export_metadata
        if self._last_export_metadata:
            payload["last_export"] = self._last_export_metadata
        return payload

    def get_all_exported_words(self) -> Set[str]:
        """Return a copy of all exported words."""
        return set(self._exported_words)

    # -------------------------------------------------------------------------
    # Export Operations
    # -------------------------------------------------------------------------

    def _sync_anki_exporter_genanki_module(self) -> None:
        """Ensure the anki_exporter module uses the latest loaded genanki."""
        import vocab_builder.anki_exporter as anki_mod

        latest_genanki = sys.modules.get("genanki")
        if latest_genanki is not None:
            anki_mod.genanki = latest_genanki

    def _resolve_default_export_directory(self) -> Path:
        """Return the stable base directory for deck-name-only exports."""
        export_directory = self._exported_words_file.parent / self.EXPORT_DIRECTORY_NAME
        if not export_directory.is_absolute():
            export_directory = self._project_root / export_directory
        return export_directory.resolve()

    def _resolve_composition_history_paths(
        self,
        history_paths: Optional[Sequence[Path]],
    ) -> Tuple[Path, ...]:
        """Return JSONL history paths that may contain composition attempts."""
        if history_paths is not None:
            return tuple(Path(path) for path in history_paths)

        from vocab_builder.compat import config_home, config_homes_for_read, get_env

        language_code = self._language_config.code
        filename = f"{language_code}_compositions.jsonl"
        base_dir_override = get_env("VOCABBUILDER_HISTORY_DIR")
        if base_dir_override:
            bases = [Path(base_dir_override)]
        else:
            primary_base = default_history_base_dir()
            bases = [primary_base]
            canonical_primary = config_home(create=True) / "history"
            bases.extend(
                candidate / "history"
                for candidate in config_homes_for_read()
                if candidate / "history" != canonical_primary
            )

        paths: List[Path] = []
        seen: Set[str] = set()
        for base in bases:
            path = Path(base) / filename
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
        return tuple(paths)

    def _resolve_template_version(self) -> str:
        """Return a stable identifier for the current Anki template."""
        anki_config = self._language_config.anki
        template_version = getattr(anki_config, "version_id", None)
        if template_version:
            return str(template_version)
        return compute_template_hash(
            [
                {"name": tpl.name, "qfmt": tpl.question_format, "afmt": tpl.answer_format}
                for tpl in anki_config.card_templates
            ],
            anki_config.card_css or "",
        )

    def _resolve_include_all(
        self,
        *,
        selected_words: Optional[Set[str]],
        include_exported_words: bool,
        template_version: str,
    ) -> Tuple[bool, bool]:
        """Return (include_all, auto_due_to_version)."""
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

        return include_all, auto_due_to_version

    @staticmethod
    def _coerce_word_type(entry: Dict[str, Any]) -> str:
        word_type = entry.get("type", "")
        if isinstance(word_type, list):
            return ", ".join(word_type)
        return str(word_type)

    @staticmethod
    def _coerce_definitions(entry: Dict[str, Any]) -> List[str]:
        definitions_list = entry.get("definitions_list")
        if not definitions_list:
            definitions_source = entry.get("definitions", "")
            definitions_list = [d.strip() for d in re.split(r";\s*", definitions_source) if d.strip()]
        return [d for d in definitions_list if d not in {"{", "}"}]

    @staticmethod
    def _coerce_examples(entry: Dict[str, Any]) -> List[Tuple[str, str]]:
        examples_list = entry.get("examples_list")
        if not examples_list:
            examples_list = []
            for example in re.split(r";\s*", entry.get("examples", "")):
                example = example.strip()
                if not example:
                    continue
                if " (" in example and example.endswith(")"):
                    fr, en = example.rsplit(" (", 1)
                    examples_list.append((fr, en[:-1]))
                else:
                    examples_list.append((example, ""))

        cleaned: List[Tuple[str, str]] = []
        for fr, en in examples_list:
            fr_clean = (fr or "").strip()
            en_clean = (en or "").strip()
            if fr_clean in {"{", "}"} and not en_clean:
                continue
            if en_clean in {"{", "}"} and not fr_clean:
                en_clean = ""
            if fr_clean or en_clean:
                cleaned.append((fr_clean, en_clean))
        return cleaned

    def _collect_entries_for_export(
        self,
        *,
        word_entries: Dict[str, Any],
        selected_words: Optional[Set[str]],
        include_all: bool,
        all_exported_words: Set[str],
    ) -> List[Tuple[str, str, AnkiExportEntry, bool]]:
        entries_for_export: List[Tuple[str, str, AnkiExportEntry, bool]] = []
        self._sync_entry_order(word_entries)
        entries_by_key = {
            self._entry_order_key(key): (key, entry)
            for key, entry in word_entries.items()
        }

        ordered_entries: List[Tuple[str, str, Any, bool]] = []
        for normalized_word in self._entry_order:
            stored_entry = entries_by_key.get(normalized_word)
            if stored_entry is None:
                continue
            key, entry = stored_entry
            already_exported = normalized_word in all_exported_words
            if selected_words is not None:
                if key not in selected_words:
                    continue
            elif already_exported and not include_all:
                continue
            ordered_entries.append((normalized_word, key, entry, already_exported))

        for export_order, item in enumerate(ordered_entries, start=1):
            normalized_word, _key, entry, already_exported = item
            export_entry = AnkiExportEntry(
                word=entry["word"],
                word_type=self._coerce_word_type(entry),
                definitions=self._coerce_definitions(entry),
                examples=self._coerce_examples(entry),
                order=export_order,
            )
            entries_for_export.append((normalized_word, entry["word"], export_entry, already_exported))

        return entries_for_export

    @staticmethod
    def _entry_order_key(word: str) -> str:
        return str(word or "").strip().lower()

    def _stable_legacy_order_key(self, word: str) -> str:
        seed = f"{self._language_config.anki.deck_namespace}::{word}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def _history_entry_order(self) -> List[str]:
        if self._entry_history_reader is None:
            return []
        try:
            records = list(self._entry_history_reader() or ())
        except (OSError, RuntimeError, TypeError, ValueError):
            return []

        records.sort(key=lambda record: str(record.get("timestamp", "")))
        ordered: List[str] = []
        seen: Set[str] = set()
        for record in records:
            if record.get("flow") != "vocab":
                continue
            if str(record.get("action") or "new") not in {"new", "force"}:
                continue
            metadata = record.get("metadata")
            saved_word = metadata.get("saved_word") if isinstance(metadata, dict) else None
            key = self._entry_order_key(saved_word or record.get("word", ""))
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)
        return ordered

    def _sync_entry_order(self, word_entries: Dict[str, Any]) -> None:
        available = {self._entry_order_key(key) for key in word_entries}
        if not available:
            # A transiently empty or unparseable vocabulary must not erase the
            # persisted acquisition order on the next tracker save.
            return

        retained = [key for key in self._entry_order if key in available]
        seen = set(retained)

        history_order = [
            key
            for key in self._history_entry_order()
            if key in available and key not in seen
        ]
        history_keys = set(history_order)
        legacy_keys = sorted(
            available - seen - history_keys,
            key=self._stable_legacy_order_key,
        )

        if retained:
            self._entry_order = retained + history_order + legacy_keys
        else:
            # Untracked entries normally predate history/order tracking. Keep
            # them ahead of known acquisitions, but deliberately decouple their
            # fallback order from the alphabetized LaTeX document.
            self._entry_order = legacy_keys + history_order

    def _compute_mistake_entries_digest(self) -> str:
        mistake_entries = []
        for entry in self._collect_mistake_entries_for_export():
            mistake_entries.append(
                {
                    "attempt_id": entry.attempt_id,
                    "correction_index": entry.correction_index,
                    "flawed_text": entry.flawed_text,
                    "corrected_text": entry.corrected_text,
                    "why_lines": list(entry.why_lines),
                    "english_intent": entry.english_intent,
                }
            )
        mistake_entries.sort(
            key=lambda entry: (
                entry["attempt_id"],
                entry["correction_index"],
                entry["flawed_text"],
                entry["corrected_text"],
                tuple(entry["why_lines"]),
                entry["english_intent"],
            )
        )
        serialized = json.dumps(
            mistake_entries,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _compute_snapshot_hash(
        self,
        word_entries: Dict[str, Any],
        *,
        include_mistake_deck: bool = False,
    ) -> str:
        """Hash all inputs that affect a complete vocabulary package."""
        self._sync_entry_order(word_entries)
        anki_config = self._language_config.anki
        entries = []
        for key, entry in sorted(
            word_entries.items(),
            key=lambda item: self._entry_order_key(item[0]),
        ):
            entries.append(
                {
                    "key": self._entry_order_key(key),
                    "word": str(entry.get("word") or ""),
                    "type": self._coerce_word_type(entry),
                    "definitions": self._coerce_definitions(entry),
                    "examples": [list(example) for example in self._coerce_examples(entry)],
                }
            )

        payload = {
            "language": self._language_config.code,
            "deck_namespace": anki_config.deck_namespace,
            "model_seed": anki_config.model_seed,
            "field_names": list(anki_config.field_names),
            "template_version": self._resolve_template_version(),
            "entry_order": list(self._entry_order),
            "entries": entries,
        }
        if include_mistake_deck:
            payload["mistake_entries_digest"] = self._compute_mistake_entries_digest()
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def register_entry_order(self, word: str) -> None:
        """Persist a newly saved word after existing order without re-sorting it."""
        with file_lock(self._exported_words_file):
            self._merge_current_export_state()
            self._vocab_repo.ensure_entries_loaded()
            key = self._entry_order_key(word)
            if not key or key in self._entry_order:
                return

            existing_entries = {
                entry_key: entry
                for entry_key, entry in self._vocab_repo.word_entries.items()
                if self._entry_order_key(entry_key) != key
            }
            self._sync_entry_order(existing_entries)
            self._entry_order.append(key)
            if not self.save_exported_words():
                self._ui.warning(
                    "The vocabulary entry was saved, but its Anki acquisition order "
                    "could not be persisted."
                )

    def _read_composition_history_records(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for path in self._composition_history_paths:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(record, dict):
                            records.append(record)
            except OSError:
                continue
        return records

    def _collect_mistake_entries_for_export(self) -> List[AnkiMistakeEntry]:
        entries: List[AnkiMistakeEntry] = []
        for record in self._read_composition_history_records():
            record_language = record.get("language")
            if record_language and record_language != self._language_config.code:
                continue
            entries.extend(self._mistake_entries_from_record(record))
        return entries

    def _mistake_entries_from_record(self, record: Dict[str, Any]) -> List[AnkiMistakeEntry]:
        attempt_id = str(record.get("attempt_id") or "").strip()
        if not attempt_id:
            return []

        corrections = record.get("corrections")
        if not isinstance(corrections, list) or not corrections:
            return []

        user_text = str(record.get("user_text") or "")
        corrected_text = str(record.get("corrected_text") or "")
        if not user_text.strip() or not corrected_text.strip():
            return []

        english_intent = self._english_intent_for_mistake_record(record)
        entries: List[AnkiMistakeEntry] = []
        for index, correction in enumerate(corrections):
            if not isinstance(correction, dict):
                continue
            entries.append(
                AnkiMistakeEntry(
                    attempt_id=attempt_id,
                    correction_index=index,
                    flawed_text=user_text,
                    corrected_text=corrected_text,
                    why_lines=self._why_lines_for_correction(correction),
                    english_intent=english_intent,
                )
            )
        return entries

    @staticmethod
    def _why_lines_for_correction(correction: Dict[str, Any]) -> List[str]:
        why = str(correction.get("why") or "").strip()
        if why:
            return [why]

        original = str(correction.get("from") or "").strip()
        replacement = str(correction.get("to") or "").strip()
        if original or replacement:
            return [f"{original} -> {replacement}".strip()]
        return []

    @staticmethod
    def _english_intent_for_mistake_record(record: Dict[str, Any]) -> str:
        if str(record.get("mode") or "").strip() == "reverse":
            return str(record.get("source_english") or "").strip()
        return str(record.get("english_gloss") or "").strip()

    def _debug_export(
        self,
        *,
        entries_for_export: List[Tuple[str, str, AnkiExportEntry, bool]],
        include_all: bool,
        selected_words: Optional[Set[str]],
        all_exported_words: Set[str],
        word_entries: Dict[str, Any],
    ) -> None:
        from vocab_builder.compat import get_env
        if not get_env("VOCABBUILDER_DEBUG_EXPORT"):
            return
        self._ui.debug(
            "[export_debug] "
            f"entries={len(entries_for_export)} include_all={include_all} "
            f"selected={selected_words} exported_words={len(all_exported_words)} "
            f"word_entries={len(word_entries)}"
        )

    def _handle_empty_export(
        self,
        *,
        entries_for_export: List[Tuple[str, str, AnkiExportEntry, bool]],
        deck_title: str,
        destination_path: Path,
        export_context: str,
        word_entries: Dict[str, Any],
        selected_words: Optional[Set[str]],
        include_all: bool,
        auto_retry_on_empty: bool,
        include_mistake_deck: bool,
        track_exported_words: bool,
        quiet: bool,
    ) -> bool:
        """Return True if the caller should stop (already handled)."""
        if entries_for_export:
            return False

        if selected_words is not None:
            self._ui.warning("None of the selected words were found or eligible for export.")
            return True
        if not word_entries:
            self._ui.warning("No vocabulary entries available to export.")
            return True
        if include_all or not auto_retry_on_empty:
            self._ui.warning(
                "No vocabulary entries qualified for Anki export. The generated deck will not contain any cards."
            )
            return True

        self._ui.info("No new words detected for export. Rebuilding deck with all tracked entries instead.")
        self.export_to_anki(
            deck_title,
            include_exported_words=True,
            selected_words=selected_words,
            auto_retry_on_empty=False,
            output_path=destination_path,
            export_context=export_context,
            include_mistake_deck=include_mistake_deck,
            track_exported_words=track_exported_words,
            quiet=quiet,
        )
        return True

    def _ensure_export_directory(self, destination_path: Path) -> Optional[Path]:
        export_directory = destination_path.parent
        try:
            export_directory.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            self._ui.error(
                f"Cannot create export directory: {export_directory}\n"
                f"Permission denied: {exc}\n"
                "Try exporting to a different location.",
                with_panel=True,
            )
            return None
        except OSError as exc:
            self._ui.error(f"Failed to create export directory: {exc}", with_panel=True)
            return None
        return export_directory

    def _write_package_atomic(
        self,
        deck: Any,
        destination_path: Path,
        export_directory: Path,
        *,
        announce: bool = True,
    ) -> Optional[Any]:
        if announce:
            self._ui.info(f"Anki deck export directory: {export_directory}")
        import genanki  # type: ignore[import]

        package = genanki.Package(deck)
        temp_path: Optional[Path] = None

        try:
            temp_fd, temp_name = tempfile.mkstemp(
                dir=export_directory,
                prefix=f".{destination_path.name}.",
                suffix=".tmp",
            )
            os.close(temp_fd)
            temp_path = Path(temp_name)
            package.write_to_file(str(temp_path))

            # Test doubles sometimes ignore the temp path entirely, leaving the
            # pre-created tempfile empty. Treat that as "no temp package".
            has_temp_package = temp_path.exists() and temp_path.stat().st_size > 0
            if has_temp_package:
                if destination_path.exists():
                    try:
                        create_backup_snapshot(destination_path, backup_suffix=".bak")
                    except OSError:
                        pass  # Best-effort backup

                os.replace(temp_path, destination_path)
            else:
                # Non-file writers (commonly used in tests) should still receive
                # the final destination path without test-only instrumentation.
                if destination_path.exists():
                    try:
                        create_backup_snapshot(destination_path, backup_suffix=".bak")
                    except OSError:
                        pass  # Best-effort backup
                package.write_to_file(str(destination_path))
            return package

        except PermissionError as exc:
            self._ui.error(
                f"Cannot write to: {destination_path}\n"
                f"Permission denied: {exc}\n\n"
                "Suggestions:\n"
                "- Check file/folder permissions\n"
                "- Try a different export location\n"
                "- Close Anki if it has the file open",
                with_panel=True,
            )
        except OSError as exc:
            if exc.errno == errno.ENOSPC or "No space left" in str(exc):
                self._ui.error(
                    "Disk full - cannot save Anki deck.\n"
                    "Free up space and try again.\n"
                    f"Target: {destination_path}",
                    with_panel=True,
                )
            else:
                self._ui.error(f"Failed to write Anki deck: {exc}", with_panel=True)
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

        return None

    def _finalize_export_state(
        self,
        *,
        entries_for_export: List[Tuple[str, str, AnkiExportEntry, bool]],
        all_exported_words: Set[str],
        deck_title: str,
        destination_path: Path,
        destination_source: str,
        template_version: str,
        export_context: str,
        include_mistake_deck: bool,
        track_exported_words: bool,
        snapshot_hash: Optional[str] = None,
        invalidate_snapshot: bool = False,
    ) -> Tuple[Set[str], Set[str]]:
        newly_added_words_normalized: Set[str] = set()
        newly_added_display: Set[str] = set()

        for normalized_word, display_word, _, already_exported in entries_for_export:
            all_exported_words.add(normalized_word)
            if not already_exported:
                newly_added_words_normalized.add(normalized_word)
                newly_added_display.add(display_word)

        if track_exported_words:
            self._exported_words = all_exported_words
            self._exported_deck_version = template_version
        if snapshot_hash is not None:
            self._snapshot_hash = snapshot_hash
            self._snapshot_export_metadata = {
                "deck_name": deck_title,
                "path": str(destination_path),
                "path_source": destination_source,
                "timestamp": time.time(),
                "total_words": len(entries_for_export),
                "include_mistake_deck": include_mistake_deck,
            }
        elif invalidate_snapshot:
            self._snapshot_hash = None
        if track_exported_words:
            self._last_export_metadata = {
                "deck_name": deck_title,
                "path": str(destination_path),
                "path_source": destination_source,
                "export_context": export_context,
                "timestamp": time.time(),
                "total_words": len(all_exported_words),
                "new_words": len(newly_added_words_normalized),
            }
        if not self.save_exported_words():
            self._ui.warning(
                "The Anki deck was written, but the exported-words tracker could not be updated."
            )
        return newly_added_words_normalized, newly_added_display

    def _matches_snapshot_destination(self, destination_path: Path) -> bool:
        metadata = self._snapshot_export_metadata
        if not isinstance(metadata, dict) or not metadata.get("path"):
            return False
        try:
            snapshot_path = Path(os.path.expanduser(str(metadata["path"]))).resolve()
            return snapshot_path == destination_path.resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def _parse_exported_words_dict(
        self,
        data: Dict[str, Any],
        path: Path,
    ) -> Tuple[Set[str], Optional[str], Optional[Dict[str, Any]]]:
        words_raw = data.get("words", [])
        words = self._coerce_string_set(words_raw)
        if words is None:
            self._preserve_invalid_export_state(path, f"invalid words field: {type(words_raw).__name__}")
            return set(), None, None

        entry_order_raw = data.get("entry_order", [])
        entry_order = self._coerce_string_list(entry_order_raw)
        if entry_order is None:
            self._ui.warning(
                "Ignoring invalid Anki entry-order metadata; a stable order will be rebuilt."
            )
            self._entry_order = []
        else:
            self._entry_order = list(dict.fromkeys(self._entry_order_key(word) for word in entry_order))

        snapshot_hash = data.get("snapshot_hash")
        if isinstance(snapshot_hash, str) and snapshot_hash.strip():
            self._snapshot_hash = snapshot_hash.strip()
        elif snapshot_hash is not None:
            self._ui.warning(
                "Ignoring invalid Anki snapshot metadata; a complete package will be rebuilt."
            )

        snapshot_export_raw = data.get("snapshot_export")
        if isinstance(snapshot_export_raw, dict):
            snapshot_export = self._normalize_loaded_export_metadata(
                snapshot_export_raw
            )
            include_mistake_deck = snapshot_export.get("include_mistake_deck", False)
            snapshot_export["include_mistake_deck"] = (
                include_mistake_deck
                if isinstance(include_mistake_deck, bool)
                else False
            )
            self._snapshot_export_metadata = snapshot_export
        elif snapshot_export_raw is not None:
            self._ui.warning(
                "Ignoring invalid Anki snapshot destination metadata."
            )

        version = data.get("deck_version")
        if version is not None and not isinstance(version, str):
            version = str(version)

        metadata_raw = data.get("last_export")
        metadata = (
            self._normalize_loaded_export_metadata(metadata_raw)
            if isinstance(metadata_raw, dict)
            else None
        )
        return words, version, metadata

    def _normalize_loaded_export_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize old cwd-derived metadata that matches the deck default file."""
        normalized = dict(metadata)
        if normalized.get("path_source"):
            return normalized

        deck_name = str(normalized.get("deck_name") or "").strip()
        raw_path = normalized.get("path")
        if not deck_name or not raw_path:
            return normalized

        try:
            previous_path = Path(os.path.expanduser(str(raw_path))).resolve()
            default_path = self._normalize_output_path(deck_name)
        except (OSError, RuntimeError, TypeError, ValueError):
            return normalized

        if previous_path == default_path:
            normalized["path_source"] = "default"
            return normalized

        if previous_path.name == default_path.name:
            normalized["path"] = str(default_path)
            normalized["path_source"] = "default"

        return normalized

    def _parse_legacy_exported_words_list(
        self,
        data: List[Any],
        path: Path,
    ) -> Tuple[Set[str], Optional[str], Optional[Dict[str, Any]]]:
        words = self._coerce_string_set(data)
        if words is None:
            self._preserve_invalid_export_state(path, "legacy export state contains non-string entries")
            return set(), None, None
        return words, None, None

    @staticmethod
    def _coerce_string_set(value: Any) -> Optional[Set[str]]:
        if value is None or isinstance(value, (str, bytes, dict)):
            return None
        try:
            items = list(value)
        except TypeError:
            return None
        if any(not isinstance(item, str) for item in items):
            return None
        return {item for item in items if item}

    @staticmethod
    def _coerce_string_list(value: Any) -> Optional[List[str]]:
        if value is None or isinstance(value, (str, bytes, dict)):
            return None
        try:
            items = list(value)
        except TypeError:
            return None
        if any(not isinstance(item, str) for item in items):
            return None
        return [item for item in items if item]

    def _preserve_invalid_export_state(self, path: Path, reason: Any) -> None:
        self._ui.warning(
            f"Exported words file is invalid ({reason}); starting fresh. "
            f"The existing state has been preserved as {path}.corrupt when possible."
        )
        if not path.exists() or not path.is_file():
            return
        try:
            shutil.copy2(path, str(path) + ".corrupt")
        except OSError:
            pass

    @staticmethod
    def _build_export_feedback(
        *,
        deck_title: str,
        destination_path: Path,
        export_directory: Path,
        all_exported_words: Set[str],
        newly_added_words_normalized: Set[str],
        newly_added_display: Set[str],
        packaged_count: int,
        template_version: str,
        auto_due_to_version: bool,
        selected_words: Optional[Set[str]],
        latex_words: Set[str],
        mistake_note_count: int = 0,
    ) -> str:
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

        if mistake_note_count:
            feedback += (
                f"\n[bold cyan]Composition mistake notes packaged: "
                f"{mistake_note_count}[/bold cyan]"
            )

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

        return feedback

    def export_to_anki(
        self,
        deck_name: Optional[str] = None,
        include_exported_words: bool = False,
        *,
        selected_words: Optional[Set[str]] = None,
        auto_retry_on_empty: bool = True,
        output_path: Optional[Path] = None,
        export_context: str = "incremental",
        include_mistake_deck: bool = False,
        track_exported_words: bool = True,
        quiet: bool = False,
    ) -> None:
        """Serialize deck generation and tracker mutation across CLI sessions."""
        with file_lock(self._exported_words_file):
            self._merge_current_export_state()
            self._export_to_anki_locked(
                deck_name,
                include_exported_words,
                selected_words=selected_words,
                auto_retry_on_empty=auto_retry_on_empty,
                output_path=output_path,
                export_context=export_context,
                include_mistake_deck=include_mistake_deck,
                track_exported_words=track_exported_words,
                quiet=quiet,
            )

    def _export_to_anki_locked(
        self,
        deck_name: Optional[str] = None,
        include_exported_words: bool = False,
        *,
        selected_words: Optional[Set[str]] = None,
        auto_retry_on_empty: bool = True,
        output_path: Optional[Path] = None,
        export_context: str = "incremental",
        include_mistake_deck: bool = False,
        track_exported_words: bool = True,
        quiet: bool = False,
    ) -> None:
        """Export vocabulary entries to an Anki deck.

        Args:
            deck_name: Name of the Anki deck to create
            include_exported_words: Include previously exported words
            selected_words: Specific words to export (lowercase keys)
            auto_retry_on_empty: Retry with all words if export produces no cards
            output_path: Explicit output location for the deck
            export_context: Context description for metadata
            include_mistake_deck: Include composition mistakes as a sibling deck
            track_exported_words: Update user-facing incremental export state
            quiet: Suppress routine progress and summary output
        """
        self._vocab_repo.ensure_entries_loaded()
        requested_deck_name = deck_name or self._language_config.anki.default_deck_name
        deck_title = self._normalize_deck_title(requested_deck_name)
        destination_input: Union[str, Path] = output_path or requested_deck_name
        try:
            destination_path = self._normalize_output_path(destination_input)
        except ValueError as exc:
            self._ui.error(f"Unsafe Anki export path: {exc}", with_panel=True)
            return
        destination_source = (
            "explicit"
            if output_path is not None or self._is_explicit_output_destination(requested_deck_name)
            else "default"
        )

        self._sync_anki_exporter_genanki_module()

        anki_config = self._language_config.anki
        template_version = self._resolve_template_version()

        exporter = AnkiExporter(deck_title, anki_config)
        word_entries = self._vocab_repo.word_entries
        if not word_entries:
            self._ui.warning("There are no vocabulary entries to export.")
            return
        latex_words = set(word_entries.keys())
        all_exported_words = set(self._exported_words)
        include_all, auto_due_to_version = self._resolve_include_all(
            selected_words=selected_words,
            include_exported_words=include_exported_words,
            template_version=template_version,
        )

        entries_for_export = self._collect_entries_for_export(
            word_entries=word_entries,
            selected_words=selected_words,
            include_all=include_all,
            all_exported_words=all_exported_words,
        )
        self._debug_export(
            entries_for_export=entries_for_export,
            include_all=include_all,
            selected_words=selected_words,
            all_exported_words=all_exported_words,
            word_entries=word_entries,
        )

        if self._handle_empty_export(
            entries_for_export=entries_for_export,
            deck_title=deck_title,
            destination_path=destination_path,
            export_context=export_context,
            word_entries=word_entries,
            selected_words=selected_words,
            include_all=include_all,
            auto_retry_on_empty=auto_retry_on_empty,
            include_mistake_deck=include_mistake_deck,
            track_exported_words=track_exported_words,
            quiet=quiet,
        ):
            return

        deck = exporter.build_deck([item[2] for item in entries_for_export])
        mistake_entries = (
            self._collect_mistake_entries_for_export()
            if include_mistake_deck
            else []
        )
        package_payload: Any = deck
        if mistake_entries:
            mistake_deck = AnkiMistakeDeckExporter(anki_config).build_deck(mistake_entries)
            package_payload = [deck, mistake_deck]
        elif include_mistake_deck:
            self._ui.warning(
                "No composition mistake records with corrections were found; "
                "exporting the vocabulary deck only."
            )

        export_directory = self._ensure_export_directory(destination_path)
        if export_directory is None:
            return

        package = self._write_package_atomic(
            package_payload,
            destination_path,
            export_directory,
            announce=not quiet,
        )
        if package is None:
            return

        packaged_count = len(entries_for_export)
        is_complete_snapshot = (
            selected_words is None
            and packaged_count == len(word_entries)
        )
        snapshot_hash = (
            self._compute_snapshot_hash(
                word_entries,
                include_mistake_deck=include_mistake_deck,
            )
            if is_complete_snapshot
            else None
        )
        invalidate_snapshot = (
            not is_complete_snapshot
            and self._matches_snapshot_destination(destination_path)
        )
        newly_added_words_normalized, newly_added_display = self._finalize_export_state(
            entries_for_export=entries_for_export,
            all_exported_words=all_exported_words,
            deck_title=deck_title,
            destination_path=destination_path,
            destination_source=destination_source,
            template_version=template_version,
            export_context=export_context,
            include_mistake_deck=include_mistake_deck,
            track_exported_words=track_exported_words,
            snapshot_hash=snapshot_hash,
            invalidate_snapshot=invalidate_snapshot,
        )

        feedback = self._build_export_feedback(
            deck_title=deck_title,
            destination_path=destination_path,
            export_directory=export_directory,
            all_exported_words=all_exported_words,
            newly_added_words_normalized=newly_added_words_normalized,
            newly_added_display=newly_added_display,
            packaged_count=packaged_count,
            template_version=template_version,
            auto_due_to_version=auto_due_to_version,
            selected_words=selected_words,
            latex_words=latex_words,
            mistake_note_count=len(mistake_entries),
        )
        if not quiet:
            self._ui.panel(feedback, title="Export Summary", border_style="green")

    def _automatic_snapshot_destination(self) -> Tuple[str, Optional[Path]]:
        """Reuse the last destination without opening an exit-time prompt."""
        default_deck = self._language_config.anki.default_deck_name
        metadata = self._snapshot_export_metadata
        if metadata is None:
            last_export = self._last_export_metadata
            if (
                isinstance(last_export, dict)
                and last_export.get("export_context") != "selected"
            ):
                metadata = last_export
        if not isinstance(metadata, dict):
            return default_deck, None

        normalized = self._normalize_loaded_export_metadata(metadata)
        deck_name = str(normalized.get("deck_name") or default_deck).strip() or default_deck
        if normalized.get("path_source") != "explicit":
            return deck_name, None

        raw_path = normalized.get("path")
        if not raw_path:
            return deck_name, None
        try:
            return deck_name, Path(os.path.expanduser(str(raw_path)))
        except (TypeError, ValueError):
            return deck_name, None

    def export_snapshot_if_changed(
        self,
        *,
        export_context: str = "clean_exit",
        quiet: bool = True,
    ) -> AnkiSnapshotResult:
        with file_lock(self._exported_words_file):
            self._merge_current_export_state()
            return self._export_snapshot_if_changed_locked(
                export_context=export_context,
                quiet=quiet,
            )

    def _export_snapshot_if_changed_locked(
        self,
        *,
        export_context: str = "clean_exit",
        quiet: bool = True,
    ) -> AnkiSnapshotResult:
        """Write a complete package when card inputs changed since the last snapshot."""
        self._vocab_repo.ensure_entries_loaded()
        word_entries = self._vocab_repo.word_entries
        if not word_entries:
            return AnkiSnapshotResult(AnkiSnapshotStatus.NO_ENTRIES)

        snapshot_metadata = self._snapshot_export_metadata
        include_mistake_deck = False
        if isinstance(snapshot_metadata, dict):
            configured_value = snapshot_metadata.get("include_mistake_deck", False)
            if isinstance(configured_value, bool):
                include_mistake_deck = configured_value

        current_hash = self._compute_snapshot_hash(
            word_entries,
            include_mistake_deck=include_mistake_deck,
        )
        if current_hash == self._snapshot_hash:
            return AnkiSnapshotResult(AnkiSnapshotStatus.UNCHANGED)

        deck_name, output_path = self._automatic_snapshot_destination()
        self.export_to_anki(
            deck_name,
            include_exported_words=True,
            auto_retry_on_empty=False,
            output_path=output_path,
            export_context=export_context,
            include_mistake_deck=include_mistake_deck,
            track_exported_words=False,
            quiet=quiet,
        )

        if self._snapshot_hash != current_hash:
            return AnkiSnapshotResult(AnkiSnapshotStatus.FAILED)

        metadata = self._snapshot_export_metadata or {}
        raw_path = metadata.get("path")
        try:
            exported_path = Path(str(raw_path)) if raw_path else None
        except (TypeError, ValueError):
            exported_path = None
        return AnkiSnapshotResult(
            AnkiSnapshotStatus.EXPORTED,
            path=exported_path,
            packaged_count=len(word_entries),
        )

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
        self._ui.panel(status_text, title="Anki Status", border_style="dim dark_orange")

        export_label = self._ui_text("menu.anki_export", f"Export {language_name} words to Anki")
        target_to_eng = self._language_config.target_to_eng
        if target_to_eng is not None:
            reconcile_fallback = (
                f"Reconcile Anki exports "
                f"({target_to_eng.source_label} -> {target_to_eng.target_label})"
            )
        else:
            reconcile_fallback = f"Reconcile {language_name} Anki exports"
        reconcile_label = self._ui_text(
            "menu.anki_reconcile",
            reconcile_fallback,
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

    def _prompt_include_mistake_deck(self) -> bool:
        mistake_count = len(self._collect_mistake_entries_for_export())
        if mistake_count <= 0:
            return False

        message = (
            f"Include composition mistake deck "
            f"'{self._language_config.anki.deck_namespace}::Mistakes' "
            f"({mistake_count} note(s))?"
        )
        confirm = getattr(self._ui, "confirm", None)
        if callable(confirm):
            return bool(confirm(message, default=True))

        self._ui.info("Including composition mistake deck by default.")
        return True

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
        except Exception as exc:
            self._ui.warning(f"Could not open interactive export menu ({exc}); defaulting to incremental mode.")
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
            include_mistake_deck = self._prompt_include_mistake_deck()
        except KeyboardInterrupt:
            self._ui.warning("Anki export cancelled.")
            return

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
            include_mistake_deck=include_mistake_deck,
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

    @staticmethod
    def _is_explicit_output_destination(candidate: Union[str, Path]) -> bool:
        """Return True when user input names a file/path rather than only a deck."""
        raw = str(candidate or "").strip()
        if not raw:
            return False
        if raw.startswith("~") or raw.lower().endswith(".apkg"):
            return True
        return any(sep in raw for sep in (os.sep, os.altsep) if sep)

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
            candidate = (self._default_export_directory / candidate).resolve()
            if not candidate.is_relative_to(self._default_export_directory):
                raise ValueError(
                    "Relative Anki export paths must stay inside "
                    f"{self._default_export_directory}"
                )
        else:
            candidate = candidate.resolve()
        return candidate

    def _determine_export_destination(self, default_deck: str) -> Tuple[str, Optional[Path], bool]:
        """Pick an Anki deck destination, reusing prior exports when possible.

        Returns:
            Tuple of (deck_title, explicit_path, reused_previous)
        """
        metadata = (
            self._normalize_loaded_export_metadata(self._last_export_metadata)
            if self._last_export_metadata
            else {}
        )
        self._last_export_metadata = metadata or self._last_export_metadata
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
            except Exception as exc:
                self._ui.warning(
                    f"Could not open destination chooser ({exc}); reusing the previous deck destination."
                )
                choice = "reuse_previous"

            if choice == "reuse_previous":
                return previous_deck, previous_path, True

        prompt_default = previous_deck or default_deck
        raw_entry = self._ui.prompt("Enter a name for your Anki deck", default=prompt_default).strip()
        if not raw_entry:
            raw_entry = prompt_default

        if self._is_explicit_output_destination(raw_entry):
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
                with file_lock(self._exported_words_file):
                    self._merge_current_export_state()
                    current_latex_entries = self._vocab_repo.get_all_latex_entries()
                    current_extras = self._exported_words - current_latex_entries
                    self._exported_words.difference_update(current_extras)
                    self.save_exported_words()
                    self._ui.success("Updated exported words; removed stale entries.")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _ui_text(self, key: str, fallback: str) -> str:
        """Get localized UI text with fallback."""
        strings = getattr(self._language_config, "ui_strings", {}) or {}
        return strings.get(key, fallback)
