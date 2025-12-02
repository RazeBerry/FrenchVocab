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


def _flush_stdin() -> None:
    """Flush any buffered input from stdin to prevent accidental keypresses."""
    if sys.platform.startswith("win"):
        try:
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getwch()
        except Exception:
            pass
        return

    try:
        import termios
        fd = sys.stdin.fileno()
        termios.tcflush(fd, termios.TCIFLUSH)
    except Exception:
        # Fallback: drain with non-blocking select
        try:
            fd = sys.stdin.fileno()
            while True:
                ready, _, _ = select.select([fd], [], [], 0)
                if not ready:
                    break
                os.read(fd, 1024)
        except Exception:
            pass


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

    # Flush any buffered input to prevent accidental double-Enter from
    # auto-selecting during spinners or previous prompts
    _flush_stdin()

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
    menu_options: list[MenuOption] = list(options)
    cancel_option = next(
        (opt for opt in menu_options if opt[0] in {"back", "cancel"}),
        None,
    )
    if cancel_option:
        cancel_key, cancel_label = cancel_option
    else:
        cancel_key, cancel_label = (None, "Cancel / Back")

    enriched_instructions = (
        f"{instructions}\n[dim]Enter 0 to cancel or return.[/dim]"
    )

    console.print(Panel(
        enriched_instructions,
        title=f"[bold #E67E50]{title}[/]",
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=False
    ))

    console.print(f"  [dim]○[/] 0. {cancel_label}")

    for idx, (key, label) in enumerate(menu_options, start=1):
        suffix = f" [dim]({key})[/dim]" if show_keys and key and key not in label else ""
        console.print(f"  [dim]○[/] {idx}. {label}{suffix}")

    prompt = "Select an option by number"
    if menu_options:
        prompt += f" [0-{len(menu_options)}]"
    prompt += " (Enter for 1, 0 to cancel): "

    while True:
        console_input = getattr(console, "input", None)
        raw = console_input(prompt) if callable(console_input) else input(prompt)
        choice = raw.strip()
        if choice == "0":
            if cancel_key is not None:
                return cancel_key
            raise KeyboardInterrupt
        if not choice and menu_options:
            return menu_options[0][0]
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(menu_options):
                return menu_options[idx - 1][0]
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
        timeouts = [0.0, _ESC_INITIAL_TIMEOUT] if not sequence else [_ESC_SEQUENCE_TIMEOUT]
        ready = False
        for timeout in timeouts:
            ready, _, _ = select.select([fd], [], [], timeout)
            if ready:
                break
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


def interactive_confirm(
    console: Console,
    message: str,
    *,
    default: bool = True,
    yes_label: str = "Yes",
    no_label: str = "No",
) -> bool:
    """Present an interactive yes/no confirmation dialog.

    Args:
        console: Rich console to render the dialog.
        message: The confirmation question to display.
        default: Default selection (True=Yes, False=No).
        yes_label: Label for the affirmative option.
        no_label: Label for the negative option.

    Returns:
        True if Yes was selected, False if No was selected.
    """
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return _fallback_confirm(console, message, default=default)

    # Flush any buffered input to prevent accidental double-Enter from
    # auto-selecting during spinners or previous prompts
    _flush_stdin()

    selected = default  # True = Yes selected, False = No selected

    console.show_cursor(False)
    try:
        with _raw_mode(sys.stdin):
            renderable = _confirm_renderable(console, message, selected, yes_label, no_label)
            with Live(renderable, console=console, refresh_per_second=24, transient=True) as live:
                while True:
                    key = _read_key()

                    if key in {"left", "up"}:
                        selected = True
                    elif key in {"right", "down"}:
                        selected = False
                    elif key == "enter":
                        return selected
                    elif key == "escape":
                        return default
                    elif key in {"y", "Y"}:
                        return True
                    elif key in {"n", "N"}:
                        return False
                    elif key == "ctrl_c":
                        raise KeyboardInterrupt

                    live.update(_confirm_renderable(console, message, selected, yes_label, no_label))
    finally:
        console.show_cursor(True)


def _confirm_renderable(
    console: Console,
    message: str,
    selected: bool,
    yes_label: str,
    no_label: str,
) -> Any:
    """Render the confirmation dialog with horizontal Yes/No options."""
    if selected:
        yes_styled = f"[black on dark_orange] → {yes_label} [/]"
        no_styled = f"   {no_label}  "
    else:
        yes_styled = f"   {yes_label}  "
        no_styled = f"[black on dark_orange] → {no_label} [/]"

    options_line = f"{yes_styled}    {no_styled}"
    instructions = "[dim]← → select • Enter confirm[/dim]"

    content = f"{message}\n\n{options_line}\n\n{instructions}"

    max_width = max(40, min(console.size.width - 6, 80))
    panel = Panel(
        content,
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=False,
        width=max_width,
        padding=(1, 2),
    )
    return Align.center(panel, vertical="middle")


def _fallback_confirm(
    console: Console,
    message: str,
    *,
    default: bool = True,
) -> bool:
    """Fallback confirmation for non-TTY environments using text input."""
    yes_tokens = {"y", "yes", "ja", "j", "oui", "o", "1", "true"}
    no_tokens = {"n", "no", "nein", "non", "0", "false"}
    default_choice = "y" if default else "n"
    suffix = "[Y/n]" if default else "[y/N]"

    while True:
        console_input = getattr(console, "input", None)
        raw = console_input(f"{message} {suffix} ") if callable(console_input) else input(f"{message} {suffix} ")
        normalized = raw.strip().casefold() or default_choice
        if normalized in yes_tokens:
            return True
        if normalized in no_tokens:
            return False
        console.print("[bold #ff6b6b]✗ Please enter Y or N.[/bold #ff6b6b]")


__all__ = ["interactive_select", "interactive_confirm"]
