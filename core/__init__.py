"""Core application modules."""

from .translator import TranslatorCLI
from .vocab import FrenchVocabBuilder  # re-export for convenience

__all__ = ["FrenchVocabBuilder", "TranslatorCLI"]
