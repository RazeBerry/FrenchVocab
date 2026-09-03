"""Read models for the complete mobile vocabulary library."""

from __future__ import annotations

from collections import Counter
import random
import threading
from typing import Any, Literal, Optional

from vocab_builder.core.text_utils import sanitize_user_text
from vocab_builder.core.vocab_application import VocabCapturePort


IndexSort = Literal["alpha", "added"]


class MobileLibrary:
    """Present repository entries without leaking LaTeX representation details."""

    def __init__(self, builder: VocabCapturePort, *, state_lock: threading.RLock):
        self.builder = builder
        self._state_lock = state_lock

    def page(
        self,
        *,
        query: str = "",
        word_type: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 200))
        needle = sanitize_user_text(query).casefold()
        type_filter = sanitize_user_text(word_type).casefold()

        entries = []
        with self._state_lock:
            for entry in self.builder.word_entries.values():
                row = entry_for_json(entry)
                searchable = " ".join(
                    [
                        row["word"],
                        row["word_type"],
                        *row["definitions"],
                        *(
                            text
                            for example in row["examples"]
                            for text in (example["source"], example["target"])
                        ),
                    ]
                ).casefold()
                if needle and needle not in searchable:
                    continue
                if type_filter and type_filter not in row["word_type"].casefold():
                    continue
                entries.append(row)

        entries.sort(key=lambda item: self.builder.normalize_word(item["word"]))
        total = len(entries)
        start = (safe_page - 1) * safe_size
        return {
            "items": entries[start : start + safe_size],
            "page": safe_page,
            "page_size": safe_size,
            "total": total,
            "has_more": start + safe_size < total,
        }

    def index(self, *, sort: IndexSort = "alpha") -> dict[str, Any]:
        """Return every entry as a finder row, with the collection's letter census.

        A letter rail has to know where each letter begins, which the paged
        endpoint cannot say, so this ships one slim row per entry instead of
        the full record the detail view loads. ``added`` reuses the acquisition
        order the Anki manager already persists, so the glossary and the deck
        agree on what "newest" means; entries that order does not know follow
        alphabetically.
        """
        with self._state_lock:
            rows = {
                key: _index_row(entry)
                for key, entry in self.builder.word_entries.items()
            }
            positions = (
                self.builder.get_anki_manager().acquisition_positions(rows.keys())
                if sort == "added"
                else {}
            )

        sort_keys = {
            key: self.builder.normalize_word(row["word"]) for key, row in rows.items()
        }
        alphabetical = sorted(rows, key=sort_keys.__getitem__)
        items = [
            rows[key]
            for key in sorted(positions, key=positions.__getitem__, reverse=True)
        ]
        items += [rows[key] for key in alphabetical if key not in positions]

        letters = Counter(_letter_bucket(value) for value in sort_keys.values())
        return {
            "items": items,
            "letters": dict(sorted(letters.items())),
            "total": len(items),
            "sort": sort,
        }

    def entry(self, word: str) -> Optional[dict[str, Any]]:
        with self._state_lock:
            existing_key = self.builder.check_duplicate(word)
            if not existing_key:
                return None
            entry = self.builder.word_entries.get(existing_key)
            return entry_for_json(entry) if entry else None

    def stats(self) -> dict[str, Any]:
        with self._state_lock:
            entries = [
                entry_for_json(value) for value in self.builder.word_entries.values()
            ]
        type_counts = Counter(
            entry["word_type"] or "Unknown"
            for entry in entries
        )
        with_examples = sum(bool(entry["examples"]) for entry in entries)
        with_multiple_senses = sum(len(entry["definitions"]) > 1 for entry in entries)
        return {
            "total": len(entries),
            "with_examples": with_examples,
            "with_multiple_senses": with_multiple_senses,
            "types": [
                {"name": name, "count": count}
                for name, count in sorted(
                    type_counts.items(),
                    key=lambda item: (-item[1], item[0].casefold()),
                )
            ],
        }

    def random_entry(self) -> Optional[dict[str, Any]]:
        with self._state_lock:
            entries = list(self.builder.word_entries.values())
        if not entries:
            return None
        return entry_for_json(random.SystemRandom().choice(entries))


def entry_for_json(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize one repository record into the public entry representation."""
    return {
        "word": str(entry.get("word", "")),
        "word_type": _type_text(entry.get("type", "")),
        "definitions": list(entry.get("definitions_list", [])),
        "examples": [
            {"source": source, "target": target}
            for source, target in entry.get("examples_list", [])
        ],
    }


def _type_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def _index_row(entry: dict[str, Any]) -> dict[str, str]:
    """Reduce one repository record to what an index row can show."""
    definitions = list(entry.get("definitions_list", []))
    return {
        "word": str(entry.get("word", "")),
        "word_type": _type_text(entry.get("type", "")),
        "gloss": str(definitions[0]) if definitions else "",
    }


def _letter_bucket(normalized_word: str) -> str:
    """File a word under the initial of the key the collection is sorted by.

    Taking the letter from the same normalized key that orders the index is
    what keeps a bucket contiguous: the key already folds accents and expands
    the ligatures that would otherwise scatter a word away from its heading
    ("OEuvre" sorts among the O's, so it is counted there).
    """
    initial = normalized_word[:1]
    return initial.upper() if initial.isascii() and initial.isalpha() else "#"


__all__ = ["IndexSort", "MobileLibrary", "entry_for_json"]
