from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import unicodedata


def normalize_word_key(word: str) -> str:
    """Lowercase + strip accents, used for stable keys."""
    word = word.lower().strip()
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

