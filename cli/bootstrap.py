"""Bootstrap helpers for the vocabulary CLI."""

from __future__ import annotations

import time
from typing import Iterable, List, Tuple

from rich.console import Console

from core import FrenchVocabBuilder
from languages import available_language_codes, get_language_config

from .navigation import interactive_select


def build_app(
    language_code: str,
    *,
    latex_file: str | None = None,
    provider: str | None = None,
    verbose: bool = False,
) -> FrenchVocabBuilder:
    """Instantiate the vocabulary builder for a specific language."""
    return FrenchVocabBuilder(
        latex_file=latex_file,
        provider=provider,
        verbose=verbose,
        language=language_code,
    )


def run_cli(argv: Iterable[str] | None = None) -> None:  # noqa: ARG001 - legacy signature
    """Launch the app after prompting for the desired language."""
    console = Console()

    try:
        language_code = _prompt_for_language(console)
    except KeyboardInterrupt:
        console.print("\n[yellow]Launch cancelled by user.[/yellow]")
        return

    start_time = time.time()
    init_start = start_time
    app = build_app(language_code)
    init_end = time.time()

    run_start = time.time()
    app.run()
    run_end = time.time()

    print(f"Total startup time: {init_end - start_time:.2f} seconds")
    print(f"Initialization time: {init_end - init_start:.2f} seconds")
    print(f"Run time: {run_end - run_start:.2f} seconds")


def _prompt_for_language(console: Console) -> str:
    options = _language_options()
    rendered = [(code, f"{name} [dim]({code})[/dim]") for code, name in options]
    return interactive_select(
        console,
        "Select Language",
        rendered,
        "Use ↑ and ↓ to choose a language. Press Enter to launch. Esc cancels.",
    )


def _language_options() -> List[Tuple[str, str]]:
    codes = available_language_codes()
    return [(code, get_language_config(code).display_name) for code in codes]


__all__ = ["build_app", "run_cli"]
