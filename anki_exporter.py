"""Tools for exporting vocabulary entries to Anki decks."""

from __future__ import annotations

import hashlib
import re
import struct
import uuid
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

import genanki


# Public API -----------------------------------------------------------------


def latex_to_anki_format(text: str) -> str:
    """Convert LaTeX formatted text into an Anki-friendly HTML string."""
    # Remove LaTeX item markers
    text = re.sub(r"\\item\s*", "", text)

    # Convert LaTeX line breaks ("\\") to HTML line breaks
    text = re.sub(r"\\\\\s*", "<br>", text)

    # Preserve command arguments while stripping command names (e.g., \textbf{mot} -> mot)
    command_pattern = re.compile(r"\\[a-zA-Z]+\*?(?P<opt>\[[^\]]*\])?(?P<brace>\{[^{}]*\})?")

    def _strip_command(match: re.Match) -> str:
        brace = match.group("brace")
        if brace:
            return brace[1:-1]
        opt = match.group("opt")
        if opt:
            return opt[1:-1]
        return ""

    text = command_pattern.sub(_strip_command, text)

    # Unescape simple LaTeX escape sequences (e.g., \% -> %)
    text = text.replace("\\%", "%").replace("\\#", "#").replace("\\$", "$")

    # Split the text into individual items and add bullet points
    items = [item.strip() for item in text.split("\n") if item.strip()]
    formatted_items = [f"• {item}" for item in items]

    formatted_text = "<br>".join(formatted_items)
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

    MODEL_SEED = "FrenchVocabModel/v1"

    def __init__(self, deck_name: str):
        self.deck_name = deck_name
        self.deck_id = self._stable_32(f"FrenchDeck::{deck_name}")
        self.model_id = self._stable_32(self.MODEL_SEED)

    def build_deck(self, entries: Iterable[AnkiExportEntry]) -> genanki.Deck:
        model = self._build_model()
        deck = genanki.Deck(self.deck_id, self.deck_name)
        for entry in entries:
            note = self._build_note(entry, model)
            deck.add_note(note)
        return deck

    # Internal helpers -----------------------------------------------------

    def _build_model(self) -> genanki.Model:
        return genanki.Model(
            self.model_id,
            "French Vocab Model v1",
            fields=[
                {"name": "French"},
                {"name": "Type"},
                {"name": "English"},
                {"name": "Example"},
            ],
            templates=[
                {
                    "name": "Card 1",
                    "qfmt": "{{French}}<br>{{Type}}",
                    "afmt": "{{FrontSide}}<hr id=\"answer\">{{English}}<br><br>Example:<br>{{Example}}",
                },
            ],
        )

    def _build_note(self, entry: AnkiExportEntry, model: genanki.Model) -> genanki.Note:
        normalized = entry.word.strip().lower()
        guid = uuid.uuid5(uuid.NAMESPACE_URL, f"fr_vocab::{normalized}").hex
        definitions_text = latex_to_anki_format(entry.definitions_text())
        examples_text = latex_to_anki_format(entry.examples_text())
        fields = [
            entry.word,
            entry.word_type,
            definitions_text,
            examples_text,
        ]
        return genanki.Note(model=model, guid=guid, fields=fields)

    @staticmethod
    def _stable_32(seed: str) -> int:
        digest = hashlib.sha1(seed.encode()).digest()
        return struct.unpack(">I", digest[:4])[0] & 0x7FFFFFFF


__all__ = [
    "AnkiExportEntry",
    "AnkiExporter",
    "latex_to_anki_format",
]
