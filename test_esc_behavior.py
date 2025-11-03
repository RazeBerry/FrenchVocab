#!/usr/bin/env python
"""Visual demonstration of ESC key behavior in menu system."""

from rich.console import Console
from rich.panel import Panel
from rich import box

def demonstrate_esc_behavior():
    """Show how ESC key works at different menu levels."""
    console = Console()

    console.print("\n[bold #E67E50]═══ ESC Key Behavior Investigation ═══[/]\n")

    # Current Implementation
    console.print(Panel(
        "[bold #E67E50]Current Implementation (Contextual ESC)[/]\n\n"
        "[bold]Main Menu:[/]\n"
        "  • ESC key → Returns 'exit' → Exits application\n"
        "  • User instruction: \"[dim]Esc exits[/dim]\"\n"
        "  • [#51cf66]✓[/] Makes sense: Top level = quit app\n\n"
        "[bold]Translation Submenu:[/]\n"
        "  • ESC key → Returns 'back' → Returns to main menu\n"
        "  • User instruction: (not explicitly shown)\n"
        "  • [#51cf66]✓[/] Makes sense: In submenu = go back\n\n"
        "[bold]Anki Tools Submenu:[/]\n"
        "  • ESC key → Returns 'back' → Returns to main menu\n"
        "  • User instruction: \"[dim]Esc returns[/dim]\"\n"
        "  • [#51cf66]✓[/] Makes sense: In submenu = go back",
        title="Design Intention",
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=True,
    ))

    # Code Flow
    console.print("\n[bold]Code Flow:[/]\n")

    code_flow = """[bold #E67E50]1. User presses ESC[/]
   ↓
[dim]cli/navigation.py:89-90[/dim]
   key in {"escape", "ctrl_c"} → raise KeyboardInterrupt
   ↓
[bold #E67E50]2. Exception caught by menu handler[/]

[bold]Main Menu Handler:[/]
   except KeyboardInterrupt:
       return "exit"  [dim]# Exits app[/dim]

[bold]Submenu Handlers (Translation, Anki):[/]
   except KeyboardInterrupt:
       return "back"  [dim]# Returns to main menu[/dim]
"""

    console.print(Panel(
        code_flow,
        title="Implementation Flow",
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=False,
    ))

    # Menu Structure
    console.print("\n[bold]Menu Structure & ESC Behavior:[/]\n")

    structure = """
    ┌─────────────────────────────────────────┐
    │         [bold #E67E50]MAIN MENU[/]                      │
    │                                         │
    │  1. Add word                            │
    │  2. Translate ────────────────┐         │
    │  3. Anki tools ──────┐        │         │
    │  4. Display vocab    │        │         │
    │  5. Settings         │        │         │
    │  6. Exit             │        │         │
    │                      │        │         │
    │  [bold yellow]ESC = EXIT APP[/]     │        │         │
    └──────────────────────┼────────┼─────────┘
                           │        │
            ┌──────────────▼──┐  ┌──▼─────────────┐
            │ [bold #E67E50]Anki Menu[/]    │  │ [bold #E67E50]Translation[/]  │
            │                 │  │ [bold #E67E50]Menu[/]           │
            │ • Export        │  │ • Eng → Fr     │
            │ • Reconcile     │  │ • Fr → Eng     │
            │ • Back          │  │ • Back         │
            │                 │  │                │
            │ [bold #51cf66]ESC = BACK[/]      │  │ [bold #51cf66]ESC = BACK[/]     │
            └─────────────────┘  └────────────────┘
"""

    console.print(structure)

    # Analysis
    console.print("\n[bold #E67E50]═══ Analysis ═══[/]\n")

    console.print("[bold]Is this behavior correct?[/]\n")
    console.print("  [#51cf66]✓[/] [bold]YES![/] This follows standard CLI conventions:\n")
    console.print("    • Vim/Emacs: ESC cancels/goes back in context")
    console.print("    • Terminal apps: ESC exits at top level")
    console.print("    • Progressive disclosure: Deeper = back, Root = exit\n")

    console.print("[bold]Potential Issues:[/]\n")
    console.print("  [#ffd43b]⚡[/] Translation menu doesn't show \"Esc returns\" instruction")
    console.print("  [#ffd43b]⚡[/] User might expect ESC on main menu to do nothing")
    console.print("  [#ffd43b]⚡[/] No explicit \"Back\" option shown (it's implicit via ESC)\n")

    console.print("[bold]Why users might be confused:[/]\n")
    console.print("  1. [dim]Main menu has explicit 'Exit' option AND ESC exits[/]")
    console.print("     → Solution: This is actually good (redundancy for different users)")
    console.print("  2. [dim]Submenus have 'Back' option AND ESC goes back[/]")
    console.print("     → Solution: Also good redundancy")
    console.print("  3. [dim]Instructions inconsistent across menus[/]")
    console.print("     → Solution: Add \"Esc returns\" to all submenu instructions\n")

    # Recommendations
    console.print(Panel(
        "[bold]Option 1: Keep Current Design (Recommended)[/]\n"
        "  • ESC exits from main menu\n"
        "  • ESC goes back from submenus\n"
        "  • [#51cf66]Fix:[/] Add \"Esc returns\" to translation menu instructions\n\n"
        "[bold]Option 2: Change Main Menu Behavior[/]\n"
        "  • ESC does nothing on main menu\n"
        "  • Must use explicit 'Exit' option\n"
        "  • [#ff6b6b]Drawback:[/] Less convenient for power users\n\n"
        "[bold]Option 3: Confirmation on Main Menu ESC[/]\n"
        "  • ESC asks \"Really exit? [Y/n]\"\n"
        "  • Prevents accidental exits\n"
        "  • [#ff6b6b]Drawback:[/] Adds friction",
        title="Design Options",
        border_style="dark_orange",
        box=box.ROUNDED,
        expand=False,
    ))

    console.print("\n[bold #E67E50]═══ Conclusion ═══[/]\n")
    console.print("[#51cf66]✓[/] ESC [bold]DOES[/] go back to previous menu (on submenus)")
    console.print("[#51cf66]✓[/] ESC exits application (on main menu)")
    console.print("[#51cf66]✓[/] This is [bold]intentional, well-designed behavior[/]\n")
    console.print("[dim]If user reports it's not working, check:[/]")
    console.print("[dim]  • Terminal emulator compatibility[/]")
    console.print("[dim]  • Key detection on their platform (Windows vs POSIX)[/]")
    console.print("[dim]  • Whether they're on main menu (where ESC = exit, not back)[/]\n")

if __name__ == "__main__":
    demonstrate_esc_behavior()
