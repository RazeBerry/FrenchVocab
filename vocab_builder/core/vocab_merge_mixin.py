"""Merge helpers extracted from VocabBuilder."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from vocab_builder.models import normalize_word_key

from .file_safety import file_lock
from .vocab_repository import EntryNotFoundError


class VocabMergeMixin:
    def _merge_into_existing_via_repo(
        self,
        key: str,
        existing_word: str,
        new_type: str,
        new_defs: List[str],
        new_examples: List[Tuple[str, str]],
    ) -> bool:
        with file_lock(self._vocab_repo.latex_file):
            success = self._vocab_repo.merge_into_existing(
                existing_word,
                new_type,
                new_defs,
                new_examples,
            )
            if not success:
                return False

            refreshed_key = self._vocab_repo.normalized_entries.get(
                self._vocab_repo.normalize_word(existing_word),
                key,
            )
            updated_entry = self.word_entries.get(refreshed_key, {})
            self._log_merge_history(
                existing_word=updated_entry.get("word", existing_word),
                final_type=updated_entry.get("type", new_type),
                merged_definitions=updated_entry.get("definitions_list", new_defs),
                merged_examples=updated_entry.get("examples_list", []),
                added_definitions=new_defs,
                added_examples=new_examples,
            )
            return True

    def _fallback_existing_definitions(self, entry: Dict[str, Any]) -> List[str]:
        definitions_list = entry.get("definitions_list") or []
        if definitions_list:
            return list(definitions_list)
        definitions_raw = entry.get("definitions", "")
        return [d.strip() for d in definitions_raw.split("; ") if d.strip()]

    def _fallback_existing_examples(self, entry: Dict[str, Any]) -> List[Tuple[str, str]]:
        examples_list = entry.get("examples_list") or []
        if examples_list:
            return list(examples_list)
        examples_raw = entry.get("examples")
        if examples_raw:
            return self._parse_examples_string(examples_raw)
        return []

    @staticmethod
    def _norm_text_for_merge(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip().lower()
        return normalize_word_key(normalized)

    def _norm_pair_for_merge(self, pair: Tuple[str, str]) -> Tuple[str, str]:
        return (self._norm_text_for_merge(pair[0]), self._norm_text_for_merge(pair[1]))

    def _dedup_merge_definitions(
        self,
        existing_defs: List[str],
        new_defs: List[str],
    ) -> tuple[List[str], List[str]]:
        merged_map: Dict[str, str] = {}
        for definition in existing_defs:
            norm_key = self._norm_text_for_merge(definition)
            if norm_key:
                merged_map[norm_key] = definition

        added: List[str] = []
        for definition in new_defs:
            norm_key = self._norm_text_for_merge(definition)
            if not norm_key:
                continue
            if norm_key in merged_map:
                continue
            merged_map[norm_key] = definition
            added.append(definition)

        return list(merged_map.values()), added

    def _dedup_merge_examples(
        self,
        existing_examples: List[Tuple[str, str]],
        new_examples: List[Tuple[str, str]],
    ) -> tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        merged_map: Dict[Tuple[str, str], Tuple[str, str]] = {}
        for pair in existing_examples:
            merged_map[self._norm_pair_for_merge(pair)] = pair

        added: List[Tuple[str, str]] = []
        for pair in new_examples:
            norm_key = self._norm_pair_for_merge(pair)
            if norm_key in merged_map:
                continue
            merged_map[norm_key] = pair
            added.append(pair)

        return list(merged_map.values()), added

    def _update_entry_in_file_checked(self, word: str, latex_block: str) -> bool:
        try:
            self.update_entry_in_file(word, latex_block)
        except EntryNotFoundError as exc:
            self.ui.error(f"Merge failed: {exc}", with_panel=True)
            return False
        except IOError as exc:
            self.ui.error(f"Merge failed - file I/O error: {exc}", with_panel=True)
            return False
        return True

    @staticmethod
    def _update_entry_memory_after_merge(
        entry: Dict[str, Any],
        final_type: str,
        merged_defs: List[str],
        merged_exs: List[Tuple[str, str]],
    ) -> None:
        entry["type"] = final_type
        entry["definitions_list"] = merged_defs
        entry["examples_list"] = merged_exs
        entry["definitions"] = "; ".join(merged_defs)
        entry["examples"] = "; ".join([f"{f} ({e})" for f, e in merged_exs])

    def _merge_into_existing_fallback(
        self,
        entry: Dict[str, Any],
        existing_word: str,
        new_type: str,
        new_defs: List[str],
        new_examples: List[Tuple[str, str]],
    ) -> bool:
        defs_existing = self._fallback_existing_definitions(entry)
        exs_existing = self._fallback_existing_examples(entry)

        merged_defs, added_defs = self._dedup_merge_definitions(defs_existing, new_defs)
        merged_exs, added_examples = self._dedup_merge_examples(exs_existing, new_examples)

        final_type = entry.get("type") or new_type
        latex_block = self.format_latex_entry(
            entry["word"],
            final_type,
            merged_defs,
            merged_exs,
            entry_command=self.entry_command,
        )

        if not self._update_entry_in_file_checked(entry["word"], latex_block):
            return False

        self._update_entry_memory_after_merge(entry, final_type, merged_defs, merged_exs)
        self._log_merge_history(
            existing_word=entry["word"],
            final_type=final_type,
            merged_definitions=merged_defs,
            merged_examples=merged_exs,
            added_definitions=added_defs,
            added_examples=added_examples,
        )
        return True

    def merge_into_existing(self, existing_word: str, new_type: str, new_defs: List[str], new_examples: List[Tuple[str, str]]) -> bool:
        """Merge new definitions/examples into an existing entry.

        Delegates core merge logic to VocabRepository while handling history logging.
        Falls back to inline implementation for test doubles without _vocab_repo.

        Returns:
            True if merge was successful, False otherwise.
        """
        # Get entry state before merge for history logging
        self._ensure_entries_loaded()
        key = existing_word.lower()
        entry = self.word_entries.get(key)
        if not entry:
            self.ui.error(f"Cannot merge: existing entry for '{existing_word}' not found.")
            return False

        # Delegate to repository if available
        if hasattr(self, "_vocab_repo"):
            return self._merge_into_existing_via_repo(key, existing_word, new_type, new_defs, new_examples)

        # Fallback for test doubles without _vocab_repo
        return self._merge_into_existing_fallback(entry, existing_word, new_type, new_defs, new_examples)
