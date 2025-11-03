#!/usr/bin/env python
"""Test script to showcase the new modern UI design."""

from ui_helper import UIHelper
from rich.console import Console

def test_modern_ui():
    """Display examples of all the modernized UI elements."""
    console = Console()
    ui = UIHelper(console)

    console.print("\n[bold #E67E50]═══ Anthropic-Themed UI Design Test ═══[/]\n")

    # Test message types with new symbols and colors
    console.print("[bold]1. Message Types with Unicode Symbols:[/]\n")
    ui.error("This is an error message with the new coral red color")
    ui.success("This is a success message with the new mint green color")
    ui.warning("This is a warning message with the new warm yellow color")
    ui.info("This is an info message with Anthropic's signature orange color")

    console.print("\n[bold]2. Panel Messages:[/]\n")
    ui.error("Critical error detected in the system", with_panel=True)
    console.print()
    ui.success("Operation completed successfully", with_panel=True)
    console.print()
    ui.warning("Please review your input", with_panel=True)
    console.print()
    ui.info("Here is some helpful information", with_panel=True)

    console.print("\n[bold]3. Regular Panels with Rounded Borders:[/]\n")
    ui.panel(
        "[bold #E67E50]Welcome to FrenchVocab![/]\n\n"
        "Your vocabulary library contains [bold #51cf66]150 words[/].\n"
        "Using LLM provider: [bold #E67E50]Anthropic Claude[/]\n"
        "Active language: [bold #E67E50]French[/]\n\n"
        "[italic dim]Version 2.0[/]",
        title="French Vocab Builder",
        border_style="dark_orange"
    )

    console.print("\n[bold]4. Menu Options Display:[/]\n")
    ui.display_menu(
        "Main Menu",
        [
            ("1", "📝 Add French word [dim](50 entries)[/dim]"),
            ("2", "🔄 Translate [dim](120 total pairs)[/dim]"),
            ("3", "📤 Export to Anki"),
            ("4", "⚙  Settings"),
            ("5", "[bold yellow3]👋 Exit[/bold yellow3]"),
        ]
    )

    console.print("\n[bold]5. Vocabulary Entry Display:[/]\n")
    ui.display_word_entry(
        word="bonjour",
        word_type="interjection",
        definitions=["Hello, good morning", "A greeting used during the day"],
        examples=[
            ("Bonjour, comment allez-vous?", "Hello, how are you?"),
            ("Bonjour à tous!", "Hello everyone!")
        ]
    )

    console.print("\n[bold]6. Performance Metrics:[/]\n")
    ui.display_metrics({
        'ttft': 0.234,
        'tps': 45.2,
        'tokens_out': 156
    })

    console.print("\n[bold #E67E50]═══ Test Complete ═══[/]\n")
    console.print("[dim]All UI elements are now using:[/]")
    console.print("  [dim]• Anthropic-inspired color palette (warm orange, coral red, mint green, warm yellow)[/]")
    console.print("  [dim]• Unicode symbols (✓, ✗, ⚡, ℹ)[/]")
    console.print("  [dim]• Rounded panel borders[/]")
    console.print("  [dim]• Enhanced visual hierarchy[/]")
    console.print("  [dim]• Warm, approachable aesthetic matching Anthropic's brand[/]\n")

if __name__ == "__main__":
    test_modern_ui()
