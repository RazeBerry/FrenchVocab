"""Tools for exporting vocabulary entries to Anki decks."""

from __future__ import annotations

import hashlib
import re
import struct
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, List, Sequence, Tuple

from languages.base import AnkiConfig

genanki: Any | None = None


def _get_genanki():
    """Return the genanki module, importing it lazily to reduce startup cost."""
    global genanki
    if genanki is None:
        import genanki as _genanki  # type: ignore[import]

        genanki = _genanki
    return genanki


# Public API -----------------------------------------------------------------


def latex_to_anki_format(text: str) -> str:
    """Convert LaTeX formatted text into an Anki-friendly HTML string."""
    # Normalize literal escape sequences into actual newlines for consistent handling
    text = text.replace("\\n", "\n")

    # Remove LaTeX item markers
    text = re.sub(r"\\item\s*", "", text)

    # Convert LaTeX line breaks ("\\") to HTML line breaks
    text = re.sub(r"\\\\\s*", "<br>", text)

    def _parse_group(source: str, start: int, opener: str, closer: str) -> tuple[str, int]:
        """Return (group_content_without_delimiters, next_index) starting at opener."""
        if start >= len(source) or source[start] != opener:
            raise ValueError("Expected group opener")
        depth = 0
        i = start
        collected: list[str] = []
        while i < len(source):
            ch = source[i]
            if ch == opener:
                depth += 1
                if depth > 1:
                    collected.append(ch)
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return "".join(collected), i + 1
                collected.append(ch)
            else:
                collected.append(ch)
            i += 1
        raise ValueError("Unbalanced group encountered")

    def _strip_latex_commands(source: str) -> str:
        """Remove LaTeX command wrappers while keeping their inner text."""
        result: list[str] = []
        i = 0
        length = len(source)

        while i < length:
            ch = source[i]
            if ch != "\\":
                result.append(ch)
                i += 1
                continue

            # Handle escaped characters like \%, \{, etc. by leaving them for later replacement.
            if i + 1 >= length or not source[i + 1].isalpha():
                result.append(ch)
                i += 1
                continue

            j = i + 1
            while j < length and (source[j].isalpha() or source[j] == "*"):
                j += 1
            idx = j
            # Skip whitespace between command and its arguments, preserving a single space if present.
            whitespace_buffer: list[str] = []
            while idx < length and source[idx].isspace():
                whitespace_buffer.append(source[idx])
                idx += 1

            content_emitted = False

            # Consume optional arguments in square brackets (discarding their content).
            while idx < length and source[idx] == "[":
                try:
                    _, idx = _parse_group(source, idx, "[", "]")
                except ValueError:
                    # On malformed input, fall back to treating the command literally.
                    result.append(source[i])
                    i += 1
                    break
            else:
                # Consume one or more braced groups, appending their stripped content.
                while idx < length and source[idx] == "{":
                    try:
                        inner, idx = _parse_group(source, idx, "{", "}")
                    except ValueError:
                        result.append(source[i])
                        i += 1
                        break
                    result.append(_strip_latex_commands(inner))
                    content_emitted = True
                else:
                    if not content_emitted:
                        # Command without braced arguments – drop the command but keep a single space if present.
                        if whitespace_buffer:
                            result.append(" ")

                i = idx
                continue

            # If we hit the break above due to malformed input, continue loop from updated i.
            continue

        return "".join(result)

    text = _strip_latex_commands(text)

    # Unescape simple LaTeX escape sequences (e.g., \% -> %)
    text = text.replace("\\%", "%").replace("\\#", "#").replace("\\$", "$")

    # Split lines into individual entries suitable for list rendering
    items = []
    for raw in text.split("\n"):
        cleaned = raw.strip()
        if not cleaned or cleaned in {"{", "}"}:
            continue
        items.append(cleaned)
    if not items:
        return ""

    list_items = "".join(f"<li>{item}</li>" for item in items)
    formatted_text = f"<ul class=\"entry-list\">{list_items}</ul>"
    return formatted_text.strip()


@dataclass
class AnkiExportEntry:
    """Structured vocabulary payload for deck export and JSON interchange."""

    word: str
    word_type: str
    definitions: Sequence[str]
    examples: Sequence[Tuple[str, str]]

    def definitions_text(self) -> str:
        return "\n".join(d.strip() for d in self.definitions if d and d.strip())

    def examples_text(self) -> str:
        rendered: List[str] = []
        for fr, en in self.examples:
            fr_part = (fr or "").strip()
            en_part = (en or "").strip()
            if not fr_part and not en_part:
                continue
            if en_part:
                rendered.append(f"{fr_part} ({en_part})" if fr_part else f"({en_part})")
            else:
                rendered.append(fr_part)
        return "\n".join(rendered)

    def to_json_dict(self) -> dict:
        """Return a JSON-serializable representation of the entry."""
        return {
            "word": self.word,
            "type": self.word_type,
            "definitions": list(self.definitions),
            "examples": [list(example) for example in self.examples],
        }


class AnkiExporter:
    """Create deterministic Anki decks from structured vocabulary entries."""

    def __init__(self, deck_name: str, config: AnkiConfig):
        self.deck_name = deck_name
        self.config = config
        self.deck_id = self._stable_32(f"{config.deck_namespace}::{deck_name}")
        self.model_id = self._stable_32(config.model_seed)

    def build_deck(self, entries: Iterable[AnkiExportEntry]) -> genanki.Deck:
        genanki_mod = _get_genanki()
        model = self._build_model()
        deck = genanki_mod.Deck(self.deck_id, self.deck_name)

        # Some test stubs provide minimal deck objects without add_note; patch in-place.
        if not hasattr(deck, "add_note"):
            deck.notes = getattr(deck, "notes", [])  # type: ignore[attr-defined]
            def _add_note(note, _deck=deck):
                _deck.notes.append(note)
            deck.add_note = _add_note  # type: ignore[attr-defined]
        if not hasattr(deck, "notes"):
            deck.notes = []  # type: ignore[attr-defined]
        if not hasattr(deck, "name"):
            deck.name = self.deck_name  # type: ignore[attr-defined]
        if not hasattr(deck, "deck_id"):
            deck.deck_id = self.deck_id  # type: ignore[attr-defined]

        for entry in entries:
            note = self._build_note(entry, model)
            deck.add_note(note)
        return deck

    # Internal helpers -----------------------------------------------------

    def _build_model(self) -> genanki.Model:
        genanki_mod = _get_genanki()
        field_defs = [{"name": name} for name in self.config.field_names]
        templates = [
            {
                "name": template.name,
                "qfmt": template.question_format,
                "afmt": template.answer_format,
            }
            for template in self.config.card_templates
        ]
        return genanki_mod.Model(
            self.model_id,
            self.config.model_name,
            fields=field_defs,
            templates=templates,
            css=self.config.card_css or None,
        )

    def _build_note(self, entry: AnkiExportEntry, model: genanki.Model) -> genanki.Note:
        genanki_mod = _get_genanki()
        normalized = entry.word.strip().lower()
        guid_namespace = self.config.deck_namespace.lower()
        guid = uuid.uuid5(uuid.NAMESPACE_URL, f"{guid_namespace}::{normalized}").hex
        definitions_text = latex_to_anki_format(entry.definitions_text())
        examples_text = latex_to_anki_format(entry.examples_text())
        field_values = [
            entry.word,
            entry.word_type,
            definitions_text,
            examples_text,
        ]
        if len(self.config.field_names) > len(field_values):
            field_values.extend(["" for _ in range(len(self.config.field_names) - len(field_values))])
        fields = field_values[:len(self.config.field_names)]
        note = genanki_mod.Note(model=model, guid=guid, fields=fields)
        if not hasattr(note, "fields"):
            note.fields = fields  # type: ignore[attr-defined]
        return note

    @staticmethod
    def _stable_32(seed: str) -> int:
        digest = hashlib.sha1(seed.encode()).digest()
        return struct.unpack(">I", digest[:4])[0] & 0x7FFFFFFF


__all__ = [
    "AnkiExportEntry",
    "AnkiExporter",
    "latex_to_anki_format",
]
