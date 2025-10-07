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


def normalize_word_key(word: str) -> str:
    """Lowercase + strip accents, used for stable keys."""
    word = _apply_replacements(word.lower().strip())
    return ''.join(
        c for c in unicodedata.normalize('NFD', word)
        if unicodedata.category(c) != 'Mn'
    )


@dataclass
class WordEntry:
    """Canonical in-memory representation of a vocab entry."""
    word: str
    type: str
    definitions: List[str]
    examples: List[Tuple[str, str]]  # list of (fr, en)

    @property
    def key(self) -> str:
        return normalize_word_key(self.word)
