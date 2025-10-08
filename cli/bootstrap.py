"""Bootstrap helpers for the vocabulary CLI."""

from __future__ import annotations

import argparse
import time
from typing import Iterable, Optional

from core import FrenchVocabBuilder
from languages import available_language_codes, default_language_code


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments, mirroring the legacy entry behaviour."""
    language_choices = available_language_codes()
    default_language_name = FrenchVocabBuilder.DEFAULT_LANGUAGE_CONFIG.display_name

    parser = argparse.ArgumentParser(
        description=f"Vocabulary Builder (default language: {default_language_name})"
    )
    parser.add_argument("latex_file", nargs="?", help="Path to LaTeX file")
    parser.add_argument(
        "--provider",
        choices=["gemini", "claude"],
        help="LLM provider to use (gemini or claude)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose diagnostics output",
    )
    parser.add_argument(
        "--language",
        choices=language_choices,
        default=default_language_code(),
        help=f"Select target language ({', '.join(language_choices)})",
    )
    return parser.parse_args(args=list(argv) if argv is not None else None)


def build_app(args: argparse.Namespace) -> FrenchVocabBuilder:
    """Instantiate the vocabulary builder using parsed arguments."""
    return FrenchVocabBuilder(
        latex_file=getattr(args, "latex_file", None),
        provider=getattr(args, "provider", None),
        verbose=bool(getattr(args, "verbose", False)),
        language=getattr(args, "language", None),
    )


def run_cli(argv: Optional[Iterable[str]] = None) -> None:
    """Entry point used by the script runner."""
    start_time = time.time()

    args = parse_args(argv)
    init_start = time.time()
    app = build_app(args)
    init_end = time.time()

    run_start = time.time()
    app.run()
    run_end = time.time()

    print(f"Total startup time: {init_end - start_time:.2f} seconds")
    print(f"Initialization time: {init_end - init_start:.2f} seconds")
    print(f"Run time: {run_end - run_start:.2f} seconds")
