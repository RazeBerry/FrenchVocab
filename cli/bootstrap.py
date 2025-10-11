"""Bootstrap helpers for the vocabulary CLI."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Iterable, List, Sequence, Tuple

from rich.console import Console
from rich.panel import Panel

from core import FrenchVocabBuilder
from languages import available_language_codes, get_language_config


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
    index = 0

    console.clear()
    console.print("")

    with _raw_mode(sys.stdin):
        while True:
            _render_language_menu(console, options, index)
            key = _read_key()
            if key == "up":
                index = (index - 1) % len(options)
            elif key == "down":
                index = (index + 1) % len(options)
            elif key == "enter":
                console.clear()
                code, name = options[index]
                console.print(f"[bold green]Selected language:[/bold green] {name} ({code})\n")
                return code
            elif key in {"escape", "ctrl_c"}:
                raise KeyboardInterrupt
            else:
                continue


def _language_options() -> List[Tuple[str, str]]:
    codes = available_language_codes()
    return [(code, get_language_config(code).display_name) for code in codes]


def _render_language_menu(console: Console, options: Sequence[Tuple[str, str]], active_index: int) -> None:
    lines = [
        "[bold cyan]Select a language to launch[/bold cyan]",
        "[dim]Use ↑ and ↓ to navigate, Enter to confirm, Esc to cancel.[/dim]",
        "",
    ]

    for index, (code, name) in enumerate(options):
        if index == active_index:
            lines.append(f"[bold green]> {name}[/bold green] [dim]({code})[/dim]")
        else:
            lines.append(f"  {name} [dim]({code})[/dim]")

    console.clear()
    console.print(Panel("\n".join(lines), border_style="blue", expand=False))


@contextmanager
def _raw_mode(stream):
    if sys.platform.startswith("win"):
        yield
        return

    import termios
    import tty

    fd = stream.fileno()
    old_attrs = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)


def _read_key() -> str:
    if sys.platform.startswith("win"):
        return _read_key_windows()
    return _read_key_posix()


def _read_key_windows() -> str:
    import msvcrt

    while True:
        ch = msvcrt.getwch()

        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            return "escape"
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            if ch2 == "H":
                return "up"
            if ch2 == "P":
                return "down"
            else:
                continue
        if ch == "\x03":
            raise KeyboardInterrupt
        # Ignore other characters
        continue


def _read_key_posix() -> str:
    ch = sys.stdin.read(1)
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x1b":
        seq = sys.stdin.read(2)
        if seq == "[A":
            return "up"
        if seq == "[B":
            return "down"
        return "escape"
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch == "":
        return "escape"
    return ch


__all__ = ["build_app", "run_cli"]
