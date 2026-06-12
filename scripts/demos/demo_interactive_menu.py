#!/usr/bin/env python
"""Showcase the interactive menu design."""

import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel


def _ensure_repo_root_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def main() -> None:
    """Display the new interactive menu styling."""
    _ensure_repo_root_on_path()
    from vocab_builder.cli.navigation import _render_menu

    console = Console()

    console.print("\n[bold #E67E50]═══ Anthropic-Themed Interactive Menu ═══[/]\n")

    # Define sample menu options
    options = [
        ("add", "📝 Add French word [dim](50 entries)[/dim]"),
        ("translate", "🔄 Translate [dim](120 total pairs)[/dim]"),
        ("export", "📤 Export to Anki"),
        ("settings", "⚙  Settings"),
        ("exit", "[bold yellow3]👋 Exit[/bold yellow3]"),
    ]

    instructions = "Use ↑ and ↓ to navigate, press Enter to select, Esc to cancel."

    # Show menu with first item selected
    console.print("[bold]State 1: First item selected[/]\n")
    lines_0 = _render_menu(options, 0, instructions, show_keys=False)
    panel_0 = Panel(
        "\n".join(lines_0),
        title="[bold #E67E50]Main Menu[/]",
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=False,
        padding=(1, 2),
    )
    console.print(panel_0)

    # Show menu with third item selected
    console.print("\n[bold]State 2: Third item selected[/]\n")
    lines_2 = _render_menu(options, 2, instructions, show_keys=False)
    panel_2 = Panel(
        "\n".join(lines_2),
        title="[bold #E67E50]Main Menu[/]",
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=False,
        padding=(1, 2),
    )
    console.print(panel_2)

    # Show menu with last item selected
    console.print("\n[bold]State 3: Last item selected[/]\n")
    lines_4 = _render_menu(options, 4, instructions, show_keys=False)
    panel_4 = Panel(
        "\n".join(lines_4),
        title="[bold #E67E50]Main Menu[/]",
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=False,
        padding=(1, 2),
    )
    console.print(panel_4)

    console.print("\n[bold #E67E50]═══ Design Features ═══[/]\n")
    console.print("  • [bold]Active item:[/] Highlighted with Anthropic orange background and → arrow")
    console.print("  • [bold]Inactive items:[/] Subtle ○ bullet point with dim styling")
    console.print("  • [bold]Panel:[/] Rounded borders with Anthropic's warm orange color scheme")
    console.print("  • [bold]Title:[/] Bold orange for warm, approachable look")
    console.print("  • [bold]Icons:[/] Emoji support for visual context")
    console.print("  • [bold]Brand:[/] Colors match Anthropic's design language\n")


if __name__ == "__main__":
    main()
