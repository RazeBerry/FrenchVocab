"""Read models for the complete mobile vocabulary library."""

from __future__ import annotations

from collections import Counter
import random
import threading
from typing import Any, Optional

from vocab_builder.core.text_utils import sanitize_user_text
from vocab_builder.core.vocab_application import VocabCapturePort


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

        entries: list[dict[str, Any]] = []
        with self._state_lock:
            for entry in self.builder.word_entries.values():
                word_type_text = _type_text(entry.get("type", ""))
                if needle and not _entry_contains(entry, needle):
                    continue
                if type_filter and type_filter not in word_type_text.casefold():
                    continue
                entries.append(entry_for_json(entry))

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

    def search_index(self, query: str, *, limit: int = 200) -> dict[str, Any]:
        """Search rich entry content but return only finder-row data.

        Search is an input hot path. Sending every matching definition and
        example made a broad query move the cold detail payload for 200 entries,
        even though the glossary renders only a word, type, and one gloss. That
        gloss is the definition that matched when one did, so the row shows the
        sense the reader searched for and the browser can mark the fragment;
        a match found only in the headword, type, or an example keeps the first
        definition. Full detail remains available from ``entry()`` on open.
        """
        needle = sanitize_user_text(query).casefold()
        safe_limit = max(1, min(limit, 200))
        if not needle:
            return {"items": [], "total": 0}

        matches: list[dict[str, Any]] = []
        with self._state_lock:
            for entry in self.builder.word_entries.values():
                gloss = _matching_gloss(entry, needle)
                if gloss is None:
                    continue
                matches.append(self._index_row(entry, gloss=gloss))

        matches.sort(key=lambda item: self.builder.normalize_word(item["word"]))
        return {
            "items": matches[:safe_limit],
            "total": len(matches),
        }

    def index(self) -> dict[str, Any]:
        """Return every entry as a finder row, with the collection's letter census.

        A letter rail has to know where each letter begins, which the paged
        endpoint cannot say, so this ships one slim row per entry instead of
        the full record the detail view loads. Rows arrive alphabetical; each
        carries its ``added`` rank from the acquisition order the Anki manager
        already persists, so the browser can reorder without another request
        and the glossary and the deck agree on what "newest" means.
        """
        with self._state_lock:
            rows = {
                key: self._index_row(entry)
                for key, entry in self.builder.word_entries.items()
            }
            positions = self.builder.get_anki_manager().acquisition_positions(rows.keys())

        # Ship the ownership fact once so A-Z and Added can switch locally.
        # Entries the order has never seen carry null and keep their
        # alphabetical place after the ranked ones in the browser's stable sort.
        for key, row in rows.items():
            row["added"] = positions.get(key)

        sort_keys = {
            key: self.builder.normalize_word(row["word"]) for key, row in rows.items()
        }
        items = [rows[key] for key in sorted(rows, key=sort_keys.__getitem__)]
        letters = Counter(row["letter"] for row in items)
        return {
            "items": items,
            "letters": dict(sorted(letters.items())),
            "total": len(items),
        }

    def _index_row(
        self, entry: dict[str, Any], *, gloss: Optional[str] = None
    ) -> dict[str, Any]:
        """Reduce one repository record to what an index row can show.

        The row names the letter it files under, taken from the same key the
        collection is sorted by, so the browser prints dividers without ever
        re-deriving the key's ligature and accent rules.
        """
        definitions = entry.get("definitions_list", [])
        first = str(definitions[0]) if definitions else ""
        word = str(entry.get("word", ""))
        return {
            "word": word,
            "word_type": _type_text(entry.get("type", "")),
            "gloss": first if gloss is None else gloss,
            "letter": _letter_bucket(self.builder.normalize_word(word)),
            # Search has no need to load acquisition state, but a stable row
            # shape avoids making the renderer polymorphic when results
            # replace the index.
            "added": None,
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
            total = 0
            with_examples = 0
            with_multiple_senses = 0
            type_counts: Counter[str] = Counter()
            for entry in self.builder.word_entries.values():
                total += 1
                type_counts[_type_text(entry.get("type", "")) or "Unknown"] += 1
                with_examples += bool(entry.get("examples_list"))
                with_multiple_senses += len(entry.get("definitions_list", [])) > 1
        return {
            "total": total,
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


def _entry_contains(entry: dict[str, Any], needle: str) -> bool:
    """Search raw entry fields without first building a rich public record."""
    if needle in str(entry.get("word", "")).casefold():
        return True
    if needle in _type_text(entry.get("type", "")).casefold():
        return True
    for definition in entry.get("definitions_list", []):
        if needle in str(definition).casefold():
            return True
    for source, target in entry.get("examples_list", []):
        if needle in str(source).casefold() or needle in str(target).casefold():
            return True
    return False


def _matching_gloss(entry: dict[str, Any], needle: str) -> Optional[str]:
    """Return the gloss a search row shows, or None when nothing matches.

    A definition containing the needle is the row's gloss, so the reader sees
    the sense they searched for rather than the first one. A match found only
    in the headword, the type, or an example keeps the first definition.
    """
    definitions = [str(definition) for definition in entry.get("definitions_list", [])]
    for definition in definitions:
        if needle in definition.casefold():
            return definition
    if _entry_contains(entry, needle):
        return definitions[0] if definitions else ""
    return None


def _letter_bucket(normalized_word: str) -> str:
    """File a word under the initial of the key the collection is sorted by.

    Taking the letter from the same normalized key that orders the index is
    what keeps a bucket contiguous: the key already folds accents and expands
    the ligatures that would otherwise scatter a word away from its heading
    ("OEuvre" sorts among the O's, so it is counted there).
    """
    initial = normalized_word[:1]
    return initial.upper() if initial.isascii() and initial.isalpha() else "#"


__all__ = ["MobileLibrary", "entry_for_json"]
