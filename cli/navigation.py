"""Interactive navigation helpers for console menus."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import IO, Any, Sequence, Tuple

from rich.console import Console
from rich.panel import Panel

MenuOption = Tuple[str, str]

_INSTRUCTION_DEFAULT = "Use ↑ and ↓ to navigate, press Enter to select, Esc to cancel."


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

    instructions = instructions or _INSTRUCTION_DEFAULT
    index = 0

    with console.screen() as screen:
        console.show_cursor(False)
        try:
            with _raw_mode(sys.stdin):
                _update_screen(screen, title, options, index, instructions, show_keys=show_keys)

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
                        _update_screen(screen, title, options, index, instructions, show_keys=show_keys)
        finally:
            console.show_cursor(True)


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
        prefix = "[bold green]>[/bold green]" if idx == active_index else "  "
        line = f"{prefix}{label}"
        if show_keys and key and key not in label:
            line = f"{line} [dim]({key})[/dim]"
        lines.append(line)

    return lines


def _update_screen(
    screen: Any,
    title: str,
    options: Sequence[MenuOption],
    index: int,
    instructions: str,
    *,
    show_keys: bool,
) -> None:
    """Render the current menu state without triggering a full terminal clear."""
    lines = _render_menu(options, index, instructions, show_keys=show_keys)
    content = "\n".join(lines)
    panel_height = len(lines) + 2  # borders add 2 rows
    screen.update(
        Panel(
            content,
            title=title,
            border_style="blue",
            expand=False,
            height=panel_height,
        )
    )


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
            continue
        if ch == "\x03":
            return "ctrl_c"
        # Ignore other characters


def _read_key_posix() -> str:
    ch = sys.stdin.read(1)

    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x1b":
        remainder = sys.stdin.read(2)
        if remainder == "[A":
            return "up"
        if remainder == "[B":
            return "down"
        return "escape"
    if ch == "\x03":
        return "ctrl_c"
    if ch == "":
        return "escape"
    return ch


__all__ = ["interactive_select"]
