"""Core application modules."""

__all__ = ["FrenchVocabBuilder", "TranslatorCLI"]


def __getattr__(name: str):
    if name == "FrenchVocabBuilder":
        from .vocab import FrenchVocabBuilder  # lazy import to avoid circular init

        return FrenchVocabBuilder
    if name == "TranslatorCLI":
        from .translator import TranslatorCLI  # lazy import to avoid startup cost

        return TranslatorCLI
    raise AttributeError(name)
