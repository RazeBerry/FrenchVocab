"""Core application modules."""

__all__ = ["VocabBuilder", "FrenchVocabBuilder", "TranslatorCLI"]


def __getattr__(name: str):
    if name in ("VocabBuilder", "FrenchVocabBuilder"):
        from .vocab import VocabBuilder  # lazy import to avoid circular init

        return VocabBuilder
    if name == "TranslatorCLI":
        from .translator import TranslatorCLI  # lazy import to avoid startup cost

        return TranslatorCLI
    raise AttributeError(name)
