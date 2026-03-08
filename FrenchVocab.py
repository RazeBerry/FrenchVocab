"""Deprecated entry point - use ``python -m vocab_builder`` or ``vocabbuilder`` instead."""

from __future__ import annotations

from typing import TYPE_CHECKING
import warnings

warnings.warn(
    "FrenchVocab.py is deprecated. Use 'vocabbuilder' or 'python -m vocab_builder' instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export for backward compatibility
from vocab_builder.cli.main import main  # noqa: E402

if TYPE_CHECKING:
    from vocab_builder.core import VocabBuilder as FrenchVocabBuilder

__all__ = ["FrenchVocabBuilder", "main"]


def __getattr__(name: str):
    if name == "FrenchVocabBuilder":
        from vocab_builder.core import FrenchVocabBuilder
        return FrenchVocabBuilder
    if name == "build_app":
        from vocab_builder.cli.bootstrap import build_app
        return build_app
    if name == "run_cli":
        from vocab_builder.cli.bootstrap import run_cli
        return run_cli
    raise AttributeError(name)


if __name__ == "__main__":
    main()
