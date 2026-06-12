#!/usr/bin/env python
"""Demonstrate consistent panel width behavior."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box


def main() -> None:
    """Demonstrate the new design system for panel widths."""
    console = Console()

    console.print("\n[bold #E67E50]═══ Panel Width Consistency Test ═══[/]\n")

    # 1. Full-Width Section Header
    console.print("[bold]1. Full-Width Section Header (expand=True):[/]\n")
    console.print(
        Panel(
            "[bold #E67E50]German → English Translator[/bold #E67E50]\n"
            "Currently managing 19 pairs in GermanToEnglish.tex",
            title="Translator Mode",
            border_style="dark_orange",
            box=box.ROUNDED,
            expand=True,  # Full-width for visual impact
        )
    )

    # 2. Wrapped Instructions Panel
    console.print("\n[bold]2. Wrapped Instructions Panel (expand=False):[/]\n")
    instructions = (
        "[#E67E50]Enter German text to translate.[/#E67E50]\n"
        "[dim]- Type or paste your text, then press Enter.\n"
        "- Press Esc to cancel.[/dim]"
    )
    console.print(Panel(instructions, border_style="dark_orange", box=box.ROUNDED, expand=False))

    # 3. Confirmation preview without visual border
    console.print("\n[bold]3. Confirmation Preview Without Borders:[/]\n")
    console.print("[dim]Streamlined layout keeps copy/paste clean—no box characters.[/dim]\n")
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="dark_orange", no_wrap=True)
    table.add_column(style="white")
    table.add_row("German:", "Guten Morgen, wie geht es Ihnen?")
    table.add_row("English:", "[bold #51cf66]Good morning, how are you?[/bold #51cf66]")
    console.print(table)

    # 4. Wrapped Warning Panel
    console.print("\n[bold]4. Wrapped Warning Panel (expand=False):[/]\n")
    warning_content = (
        "This German phrase already exists:\n\n"
        "  [bold #E67E50]German:[/bold #E67E50] Hallo Welt\n"
        "  [bold magenta]English:[/bold magenta] Hello World"
    )
    console.print(Panel(warning_content, title="Duplicate Found", border_style="yellow3", box=box.ROUNDED, expand=False))

    # 5. Another Full-Width Header for Comparison
    console.print("\n[bold]5. Another Full-Width Header (expand=True):[/]\n")
    console.print(
        Panel(
            "[bold #E67E50]French Vocabulary Builder[/bold #E67E50]\n"
            "Your library contains 150 words | Using: Anthropic Claude",
            title="Welcome",
            border_style="dark_orange",
            box=box.ROUNDED,
            expand=True,
        )
    )

    # Design Principle Summary
    console.print("\n[bold #E67E50]═══ Design Principles ═══[/]\n")
    console.print("[bold]Full-Width Panels (expand=True):[/]")
    console.print("  • Major section headers and mode indicators")
    console.print("  • Welcome/exit screens")
    console.print("  • Content that needs visual weight and hierarchy\n")

    console.print("[bold]Wrapped Panels (expand=False):[/]")
    console.print("  • Instructions and helper text")
    console.print("  • Inline menus")
    console.print("  • Warnings and alerts")
    console.print("  • Contextual info that benefits from borders\n")

    console.print("[bold]Borderless Layouts:[/]")
    console.print("  • Translation confirmation previews")
    console.print("  • Content users frequently copy or share\n")

    console.print("[bold]Why This Matters:[/]")
    console.print("  • [#51cf66]✓[/#51cf66] Consistent visual hierarchy")
    console.print("  • [#51cf66]✓[/#51cf66] Users quickly understand structure")
    console.print("  • [#51cf66]✓[/#51cf66] Professional, cohesive design")
    console.print("  • [#51cf66]✓[/#51cf66] Follows Anthropic's design language\n")


if __name__ == "__main__":
    main()
