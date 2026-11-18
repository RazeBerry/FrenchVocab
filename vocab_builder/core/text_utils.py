"""Shared text normalization and labeling helpers."""

from __future__ import annotations

from functools import lru_cache
import unicodedata
from typing import Any, Callable

from vocab_builder.languages import TranslatorConfig
from vocab_builder.models import normalize_word_key


_ZERO_WIDTH_CHARS = ("\u00AD", "\u200B", "\u200C", "\u200D", "\u2060", "\ufeff")


def sanitize_user_text(text: str) -> str:
    """Normalize user input before validation."""
    normalized = unicodedata.normalize("NFC", text.strip())
    normalized = normalized.replace("’", "'").replace("‘", "'")
    for ch in _ZERO_WIDTH_CHARS:
        if ch in normalized:
            normalized = normalized.replace(ch, "")
    return normalized


def fold_marks(text: str, headword_key: Callable[[str], str]) -> str:
    """Strip combining marks except from the letters a language keys apart.

    A marked letter keeps its marks when the language's headword key tells it
    from its unmarked base while the shared default key does not (Polish
    ``ą`` is not ``a``). For a language keyed by ``normalize_word_key`` the
    two conditions contradict, so nothing is kept and the result is the plain
    mark-stripped text (docs/vocabulary.md).
    """
    composed = unicodedata.normalize("NFC", text)
    pieces = []
    run_start = 0
    for index, char in enumerate(composed):
        if _keyed_apart(headword_key, char):
            pieces.append(_strip_marks(composed[run_start:index]))
            pieces.append(char)
            run_start = index + 1
    pieces.append(_strip_marks(composed[run_start:]))
    return "".join(pieces)


@lru_cache(maxsize=None)
def _keyed_apart(headword_key: Callable[[str], str], char: str) -> bool:
    base = _strip_marks(char)
    return (
        headword_key(char) != headword_key(base)
        and normalize_word_key(char) == normalize_word_key(base)
    )


def _strip_marks(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )


def detect_input_type(text: str) -> str:
    """Classify input as `word`, `expression`, or `sentence`."""
    if not text:
        return "word"
    candidate = text.strip()
    if "\n" in candidate:
        return "sentence"
    if any(p in candidate for p in ".!?;:") or len(candidate) > 120:
        return "sentence"
    word_count = len(candidate.split())
    if word_count >= 9:
        return "sentence"
    if word_count >= 2:
        return "expression"
    return "word"


def translator_title(config: TranslatorConfig | Any) -> str:
    """Return a stable display title for translator configs."""
    title = getattr(config, "ui_title", None)
    if title:
        return title
    source = getattr(config, "source_label", "Source")
    target = getattr(config, "target_label", "Target")
    return f"{source} → {target} Translator"
