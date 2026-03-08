"""Shared text normalization and labeling helpers."""

from __future__ import annotations

import unicodedata
from typing import Any

from vocab_builder.languages import TranslatorConfig


_ZERO_WIDTH_CHARS = ("\u00AD", "\u200B", "\u200C", "\u200D", "\u2060", "\ufeff")


def sanitize_user_text(text: str) -> str:
    """Normalize user input before validation."""
    normalized = unicodedata.normalize("NFC", text.strip())
    normalized = normalized.replace("’", "'").replace("‘", "'")
    for ch in _ZERO_WIDTH_CHARS:
        if ch in normalized:
            normalized = normalized.replace(ch, "")
    return normalized


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
