from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import unicodedata

_SPECIAL_REPLACEMENTS = (
    ("ß", "ss"),
    ("ä", "ae"),
    ("ö", "oe"),
    ("ü", "ue"),
    ("æ", "ae"),
    ("œ", "oe"),
)


def _apply_replacements(word: str) -> str:
    """Expand language-specific ligatures and digraphs before accent stripping."""
    for original, replacement in _SPECIAL_REPLACEMENTS:
        if original in word:
            word = word.replace(original, replacement)
    return word


def fold_word_text(text: str) -> str:
    """Lowercase, expand ligatures and digraphs, and strip accents; keep spacing."""
    text = _apply_replacements(text.lower())
    return ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )


def normalize_word_key(word: str) -> str:
    """Lowercase + strip accents, used for stable keys."""
    return fold_word_text(word.strip())


@dataclass
class WordEntry:
    """Canonical in-memory representation of a vocab entry."""
    word: str
    type: str
    definitions: List[str]
    examples: List[Tuple[str, str]]  # list of (fr, en)
