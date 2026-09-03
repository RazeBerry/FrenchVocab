"""Tools for exporting vocabulary entries to Anki decks."""

from __future__ import annotations

import html
import hashlib
import re
import struct
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, List, Sequence, Tuple

from vocab_builder.languages.base import AnkiConfig

genanki: Any | None = None
_HTML_BREAK_TOKEN = "__FRENCHVOCAB_ANKI_BR__"


def _get_genanki():
    """Return the genanki module, importing it lazily to reduce startup cost."""
    global genanki
    if genanki is None:
        import genanki as _genanki  # type: ignore[import]

        genanki = _genanki
    return genanki


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


def _read_command_name(source: str, start: int) -> int:
    """Return index after reading a LaTeX command name starting at start."""
    idx = start
    while idx < len(source) and (source[idx].isalpha() or source[idx] == "*"):
        idx += 1
    return idx


def _consume_whitespace(source: str, start: int) -> tuple[bool, int]:
    """Return (had_whitespace, next_index)."""
    idx = start
    had_ws = False
    while idx < len(source) and source[idx].isspace():
        had_ws = True
        idx += 1
    return had_ws, idx


def _skip_optional_args(source: str, start: int) -> int:
    """Skip any optional args like [...], returning the next index."""
    idx = start
    while idx < len(source) and source[idx] == "[":
        _, idx = _parse_group(source, idx, "[", "]")
    return idx


def _consume_braced_groups(source: str, start: int) -> tuple[str, int, bool]:
    """Consume one or more {...} groups, returning (text, next_index, emitted_any)."""
    idx = start
    emitted: list[str] = []
    content_emitted = False
    while idx < len(source) and source[idx] == "{":
        inner, idx = _parse_group(source, idx, "{", "}")
        emitted.append(_strip_latex_commands(inner))
        content_emitted = True
    return "".join(emitted), idx, content_emitted


def _strip_latex_command(source: str, start: int) -> tuple[str, int] | None:
    """Strip a single LaTeX command at source[start], returning (text, next_index).

    Returns None to signal that the backslash should be treated literally.
    """
    if start + 1 >= len(source) or not source[start + 1].isalpha():
        return None

    idx = _read_command_name(source, start + 1)
    had_ws, idx = _consume_whitespace(source, idx)

    try:
        idx = _skip_optional_args(source, idx)
        inner_text, idx, content_emitted = _consume_braced_groups(source, idx)
    except ValueError:
        return None

    if content_emitted:
        return inner_text, idx
    if had_ws:
        return " ", idx
    return "", idx


def _strip_latex_commands(source: str) -> str:
    """Remove LaTeX command wrappers while keeping their inner text."""
    result: list[str] = []
    i = 0
    while i < len(source):
        ch = source[i]
        if ch != "\\":
            result.append(ch)
            i += 1
            continue

        stripped = _strip_latex_command(source, i)
        if stripped is None:
            result.append(ch)
            i += 1
            continue

        emitted, i = stripped
        if emitted:
            result.append(emitted)

    return "".join(result)


def _normalize_latex_text(text: str) -> str:
    # Normalize literal escape sequences into actual newlines for consistent handling
    text = text.replace("\\n", "\n")

    # Remove LaTeX item markers
    text = re.sub(r"\\item\s*", "", text)

    # Convert LaTeX line breaks ("\\") to HTML line breaks
    text = re.sub(r"\\\\\s*", _HTML_BREAK_TOKEN, text)

    return text


def _extract_nonempty_items(text: str) -> List[str]:
    items: List[str] = []
    for raw in text.split("\n"):
        cleaned = raw.strip()
        if not cleaned or cleaned in {"{", "}"}:
            continue
        items.append(cleaned)
    return items


def _render_safe_html_item(item: str) -> str:
    return html.escape(item, quote=True).replace(_HTML_BREAK_TOKEN, "<br>")


# Public API -----------------------------------------------------------------


def latex_to_anki_format(text: str) -> str:
    """Convert LaTeX formatted text into an Anki-friendly HTML string."""
    text = _normalize_latex_text(text)
    text = _strip_latex_commands(text)

    # Unescape simple LaTeX escape sequences (e.g., \% -> %)
    text = text.replace("\\%", "%").replace("\\#", "#").replace("\\$", "$")

    # Split lines into individual entries suitable for list rendering
    items = _extract_nonempty_items(text)
    if not items:
        return ""

    list_items = "".join(f"<li>{_render_safe_html_item(item)}</li>" for item in items)
    formatted_text = f"<ul class=\"entry-list\">{list_items}</ul>"
    return formatted_text.strip()


@dataclass
class AnkiExportEntry:
    """Structured vocabulary payload for deck export."""

    word: str
    word_type: str
    definitions: Sequence[str]
    examples: Sequence[Tuple[str, str]]
    order: int = 0

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


@dataclass
class AnkiMistakeEntry:
    """Structured composition-mistake payload for deck export."""

    attempt_id: str
    correction_index: int
    flawed_text: str
    corrected_text: str
    why_lines: Sequence[str]
    english_intent: str = ""

    def why_text(self) -> str:
        return "\n".join(line.strip() for line in self.why_lines if line and line.strip())


_MISTAKE_FIELD_NAMES = ("FlawedText", "CorrectedText", "WhyLines", "EnglishIntent")

_MISTAKE_FIX_FRONT_TEMPLATE = """
<div class="entry-card entry-card--front mistake-card mistake-card--fix">
  <div class="entry-section-title">Find the error(s)</div>
  <div class="entry-content mistake-text">{{FlawedText}}</div>
</div>
""".strip()

_MISTAKE_FIX_BACK_TEMPLATE = """
<div class="entry-card entry-card--back mistake-card mistake-card--fix">
  <div class="entry-section">
    <div class="entry-section-title">Corrected text</div>
    <div class="entry-content mistake-text">{{CorrectedText}}</div>
  </div>
  {{#WhyLines}}
  <div class="entry-section">
    <div class="entry-section-title">Why</div>
    <div class="entry-content mistake-text">{{WhyLines}}</div>
  </div>
  {{/WhyLines}}
</div>
""".strip()

_MISTAKE_PRODUCE_FRONT_TEMPLATE = """
{{#EnglishIntent}}
<div class="entry-card entry-card--front mistake-card mistake-card--produce">
  <div class="entry-section-title">Produce this</div>
  <div class="entry-content mistake-text">{{EnglishIntent}}</div>
</div>
{{/EnglishIntent}}
""".strip()

_MISTAKE_PRODUCE_BACK_TEMPLATE = """
<div class="entry-card entry-card--back mistake-card mistake-card--produce">
  <div class="entry-section">
    <div class="entry-section-title">Idiomatic version</div>
    <div class="entry-content mistake-text">{{CorrectedText}}</div>
  </div>
</div>
""".strip()

_MISTAKE_CARD_CSS = """
.mistake-card .entry-section-title {
    text-transform: uppercase;
}

.mistake-text {
    white-space: normal;
}
""".strip()


class AnkiMistakeDeckExporter:
    """Create a deterministic Anki deck from composition mistake history."""

    def __init__(self, config: AnkiConfig):
        self.config = config
        self.namespace = config.deck_namespace
        self.deck_name = f"{self.namespace}::Mistakes"
        self.deck_id = AnkiExporter._stable_32(self.deck_name)
        self.model_id = AnkiExporter._stable_32(f"{self.namespace}::MistakeModel/v1")

    def build_deck(self, entries: Iterable[AnkiMistakeEntry]) -> genanki.Deck:
        genanki_mod = _get_genanki()
        model = self._build_model()
        deck = genanki_mod.Deck(self.deck_id, self.deck_name)

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
            deck.add_note(self._build_note(entry, model))
        return deck

    def _build_model(self) -> genanki.Model:
        genanki_mod = _get_genanki()
        css_parts = [self.config.card_css] if self.config.card_css else []
        css_parts.append(_MISTAKE_CARD_CSS)
        return genanki_mod.Model(
            self.model_id,
            f"{self.namespace} Mistake Model v1",
            fields=[{"name": name} for name in _MISTAKE_FIELD_NAMES],
            templates=[
                {
                    "name": "Fix-this",
                    "qfmt": _MISTAKE_FIX_FRONT_TEMPLATE,
                    "afmt": _MISTAKE_FIX_BACK_TEMPLATE,
                },
                {
                    "name": "Produce-this",
                    "qfmt": _MISTAKE_PRODUCE_FRONT_TEMPLATE,
                    "afmt": _MISTAKE_PRODUCE_BACK_TEMPLATE,
                },
            ],
            css="\n\n".join(css_parts) or None,
        )

    def _build_note(self, entry: AnkiMistakeEntry, model: genanki.Model) -> genanki.Note:
        genanki_mod = _get_genanki()
        guid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{self.namespace}::mistake::{entry.attempt_id}::{entry.correction_index}",
        ).hex
        fields = [
            _plain_text_to_anki_html(entry.flawed_text),
            _plain_text_to_anki_html(entry.corrected_text),
            _plain_text_to_anki_html(entry.why_text()),
            _plain_text_to_anki_html(entry.english_intent),
        ]
        note = genanki_mod.Note(model=model, guid=guid, fields=fields)
        if not hasattr(note, "fields"):
            note.fields = fields  # type: ignore[attr-defined]
        return note


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

        for position, entry in enumerate(entries, start=1):
            note = self._build_note(entry, model, fallback_order=position)
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

    def _build_note(
        self,
        entry: AnkiExportEntry,
        model: genanki.Model,
        *,
        fallback_order: int,
    ) -> genanki.Note:
        genanki_mod = _get_genanki()
        normalized = entry.word.strip().lower()
        guid_headword = self.config.guid_headword_aliases.get(normalized, normalized)
        guid_headword = guid_headword.strip().lower()
        guid_namespace = self.config.deck_namespace.lower()
        guid = uuid.uuid5(uuid.NAMESPACE_URL, f"{guid_namespace}::{guid_headword}").hex
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
        # Anki recomputes sfld from the headword on import, so due is the only
        # channel that carries acquisition order.
        note.due = entry.order if entry.order > 0 else fallback_order
        return note

    @staticmethod
    def _stable_32(seed: str) -> int:
        digest = hashlib.sha1(seed.encode()).digest()
        return struct.unpack(">I", digest[:4])[0] & 0x7FFFFFFF


def _plain_text_to_anki_html(text: object) -> str:
    escaped = html.escape(str(text or ""), quote=False)
    return escaped.replace("\n", "<br>")


__all__ = [
    "AnkiExportEntry",
    "AnkiExporter",
    "AnkiMistakeDeckExporter",
    "AnkiMistakeEntry",
    "latex_to_anki_format",
]
