"""Bootstrap helpers for the vocabulary CLI."""

from __future__ import annotations

from typing import Iterable, List, Tuple, TYPE_CHECKING

from rich.console import Console

from languages import available_language_codes, get_language_config

if TYPE_CHECKING:  # pragma: no cover - avoid circular imports
    from core import FrenchVocabBuilder

from .navigation import interactive_select


def build_app(
    language_code: str,
    *,
    latex_file: str | None = None,
    provider: str | None = None,
    verbose: bool = False,
    eager_provider: bool = False,
) -> FrenchVocabBuilder:
    """Instantiate the vocabulary builder for a specific language."""
    from core import FrenchVocabBuilder  # Local import to avoid circular dependency

    return FrenchVocabBuilder(
        latex_file=latex_file,
        provider=provider,
        verbose=verbose,
        language=language_code,
        eager_provider=eager_provider,
    )


def run_cli(
    argv: Iterable[str] | None = None,  # noqa: ARG001 - legacy signature
    *,
    latex_file: str | None = None,
    provider: str | None = None,
    verbose: bool = False,
    eager_provider: bool = False,
) -> None:
    """Launch the app after prompting for the desired language."""
    console = Console()

    try:
        language_code = _prompt_for_language(console)
    except KeyboardInterrupt:
        console.print("\n[yellow]Launch cancelled by user.[/yellow]")
        return

    app = build_app(
        language_code,
        latex_file=latex_file,
        provider=provider,
        verbose=verbose,
        eager_provider=eager_provider,
    )
    app.run()


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
