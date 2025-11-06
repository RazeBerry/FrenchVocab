"""Core application modules."""

from .translator import TranslatorCLI

__all__ = ["FrenchVocabBuilder", "TranslatorCLI"]


def __getattr__(name: str):
    if name == "FrenchVocabBuilder":
        from .vocab import FrenchVocabBuilder  # lazy import to avoid circular init

        return FrenchVocabBuilder
    raise AttributeError(name)
