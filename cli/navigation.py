"""Interactive navigation helpers for console menus."""

from __future__ import annotations

import os
import select
import sys
from contextlib import contextmanager
from typing import IO, Any, Sequence, Tuple

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich import box

try:
    from rich.live import Live
except ImportError:  # pragma: no cover - used when Rich stubs are installed
    from contextlib import contextmanager

    @contextmanager
    def Live(*_args, **_kwargs):
        class _NoOpLive:
            def update(self, *_a, **_k) -> None:
                pass

        yield _NoOpLive()

MenuOption = Tuple[str, str]

_INSTRUCTION_DEFAULT = "Use ↑ and ↓ to navigate, press Enter to select, Esc to cancel."
_ESC_INITIAL_TIMEOUT = 0.015  # fast path when ESC is pressed alone without clipping arrow keys
_ESC_SEQUENCE_TIMEOUT = 0.03  # follow-up polling window once a sequence begins
_MAX_ESCAPE_SEQUENCE_BYTES = 5


def interactive_select(
    console: Console,
    title: str,
    options: Sequence[MenuOption],
    instructions: str | None = None,
    *,
    show_keys: bool = False,
) -> str:
    """Present an interactive menu and return the key of the selected option.

    Args:
        console: Rich console to render the menu.
        title: Panel title.
        options: Sequence of (key, label) pairs.
        instructions: Optional helper text displayed above the menu.
        show_keys: Append the option key to the rendered label when True.

    Returns:
        The key associated with the chosen option.

    Raises:
        KeyboardInterrupt: If the user presses Esc or Ctrl+C.
        ValueError: If options is empty.
    """
    if not options:
        raise ValueError("interactive_select requires at least one option.")

    if not getattr(sys.stdin, "isatty", lambda: False)():
        instructions = instructions or _INSTRUCTION_DEFAULT
        return _fallback_interactive_select(
            console,
            title,
            options,
            instructions,
            show_keys=show_keys,
        )

    instructions = instructions or _INSTRUCTION_DEFAULT
    index = 0

    console.show_cursor(False)
    try:
        with _raw_mode(sys.stdin):
            renderable = _menu_renderable(
                console, title, options, index, instructions, show_keys=show_keys
            )
            with Live(renderable, console=console, refresh_per_second=24, transient=True) as live:
                while True:
                    key = _read_key()
                    previous_index = index

                    if key == "up":
                        index = (index - 1) % len(options) if len(options) > 1 else index
                    elif key == "down":
                        index = (index + 1) % len(options) if len(options) > 1 else index
                    elif key == "enter":
                        return options[index][0]
                    elif key in {"escape", "ctrl_c"}:
                        raise KeyboardInterrupt

                    if index != previous_index:
                        live.update(
                            _menu_renderable(
                                console,
                                title,
                                options,
                                index,
                                instructions,
                                show_keys=show_keys,
                            )
                        )
    finally:
        console.show_cursor(True)


def _fallback_interactive_select(
    console: Console,
    title: str,
    options: Sequence[MenuOption],
    instructions: str,
    *,
    show_keys: bool,
) -> str:
    console.print(Panel(
        instructions,
        title=f"[bold #E67E50]{title}[/]",
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=False
    ))

    for idx, (key, label) in enumerate(options, start=1):
        suffix = f" [dim]({key})[/dim]" if show_keys and key and key not in label else ""
        console.print(f"  [dim]○[/] {idx}. {label}{suffix}")

    prompt = "Select an option by number"
    if options:
        prompt += f" [1-{len(options)}]"
    prompt += " (Enter for 1): "

    while True:
        console_input = getattr(console, "input", None)
        raw = console_input(prompt) if callable(console_input) else input(prompt)
        choice = raw.strip()
        if not choice and options:
            return options[0][0]
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        console.print("[bold #ff6b6b]✗ Invalid selection. Please enter a valid option number.[/bold #ff6b6b]")


def _render_menu(
    options: Sequence[MenuOption],
    active_index: int,
    instructions: str,
    *,
    show_keys: bool,
) -> list[str]:
    lines: list[str] = []
    if instructions:
        lines.append(f"[dim]{instructions}[/dim]")
        lines.append("")

    for idx, (key, label) in enumerate(options):
        if idx == active_index:
            # Active item with Anthropic orange background highlight
            line = f"[black on dark_orange] → {label} [/]"
        else:
            # Inactive item with subtle bullet
            line = f"  [dim]○[/] {label}"

        if show_keys and key and key not in label:
            line = f"{line} [dim]({key})[/dim]"
        lines.append(line)

    return lines


def _menu_renderable(
    console: Console,
    title: str,
    options: Sequence[MenuOption],
    index: int,
    instructions: str,
    *,
    show_keys: bool,
) -> Any:
    lines = _render_menu(options, index, instructions, show_keys=show_keys)
    content = "\n".join(lines)
    max_width = max(32, min(console.size.width - 6, 96))
    panel = Panel(
        content,
        title=f"[bold #E67E50]{title}[/]",
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=False,
        width=max_width,
        padding=(1, 2),
    )
    return Align.center(panel, vertical="middle")


@contextmanager
def _raw_mode(stream: IO[Any]):
    if sys.platform.startswith("win"):
        yield
        return

    import termios
    import tty

    fd = stream.fileno()
    original_attrs = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)
        no_echo_attrs = termios.tcgetattr(fd)
        no_echo_attrs[3] &= ~termios.ECHO  # disable echo while in interactive menu
        termios.tcsetattr(fd, termios.TCSANOW, no_echo_attrs)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original_attrs)


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
            # Preserve legacy behaviour for unrecognised extended keys; ConPTY quirks
            # require manual validation before tightening this path.
            continue
        if ch == "\x03":
            return "ctrl_c"
        # Ignore other characters


def _read_key_posix() -> str:
    fd = sys.stdin.fileno()
    raw = os.read(fd, 1)
    ch = raw.decode("utf-8", "ignore")

    if ch == "":
        return "escape"
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x03":
        return "ctrl_c"
    if ch != "\x1b":
        return ch

    sequence: list[str] = []
    for _ in range(_MAX_ESCAPE_SEQUENCE_BYTES):
        timeout = _ESC_INITIAL_TIMEOUT if not sequence else _ESC_SEQUENCE_TIMEOUT
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            break
        next_raw = os.read(fd, 1)
        if not next_raw:
            break
        next_ch = next_raw.decode("utf-8", "ignore")
        if not next_ch:
            break
        sequence.append(next_ch)

    remainder = "".join(sequence)
    if remainder in {"[A", "OA"}:
        return "up"
    if remainder in {"[B", "OB"}:
        return "down"
    if remainder in {"[C", "OC"}:
        return "right"
    if remainder in {"[D", "OD"}:
        return "left"
    return "escape"


__all__ = ["interactive_select"]
