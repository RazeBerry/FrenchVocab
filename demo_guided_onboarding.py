#!/usr/bin/env python3
"""
Demo script to visualize the new guided onboarding flow.
This shows what a new user will experience.
"""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()

def demo_guided_flow():
    """Simulate the guided onboarding experience."""

    # Initial welcome screen
    console.print()
    console.print(Panel(
        "[bold cyan]🚀 Welcome to FrenchVocab![/bold cyan]\n\n"
        "To translate words, you need an AI provider.\n\n"
        "[bold]Choose your setup experience:[/bold]",
        title="First-Time Setup",
        border_style="cyan",
    ))

    console.print("\n[bold green]✨ Guided Setup[/bold green] [dim](Recommended for beginners)[/dim]")
    console.print("   Quick 3-step setup with Google Gemini (free tier available)\n")
    console.print("⚙️  Advanced Setup")
    console.print("   Choose provider, storage method, and more options\n")

    choice = Prompt.ask("Select", choices=["guided", "advanced"], default="guided")

    if choice == "advanced":
        console.print("\n[yellow]Advanced mode selected. (Not shown in this demo)[/yellow]")
        return

    # Step 1: API Key Instructions
    console.print()
    console.print(Panel(
        "[bold]Step 1/3: Get Your Free API Key[/bold]\n\n"
        "We'll use Google Gemini (free tier: 60 requests/minute).\n\n"
        "[cyan]What you need to do:[/cyan]\n"
        "1. Visit: [bold]https://ai.google.dev/[/bold]\n"
        "2. Click [bold]\"Get API Key\"[/bold] or [bold]\"API Keys\"[/bold]\n"
        "3. Sign in with your Google account\n"
        "4. Click [bold]\"Create API Key\"[/bold]\n"
        "5. Copy the key (starts with [bold]AIza...[/bold])\n\n"
        "✨ [dim]Tip: The key is free and takes ~1 minute to generate![/dim]",
        title="🔑 API Key Needed",
        border_style="blue",
    ))

    Prompt.ask("\nPress Enter when you have your API key ready", default="")

    # Step 2: Key Entry
    console.print()
    console.print(Panel(
        "[bold]Step 2/3: Enter Your API Key[/bold]\n\n"
        "Paste your Gemini API key below.\n"
        "[dim]Input is hidden for security.[/dim]",
        title="🔐 Secure Input",
        border_style="yellow",
    ))

    console.print("\n[dim](In real usage, your key input would be hidden)[/dim]")
    api_key = Prompt.ask("Enter your Google Gemini API key", default="AIzaSy...")

    console.print("\n[cyan]Testing connection to Google Gemini...[/cyan]")
    import time
    time.sleep(1)
    console.print("[bold green]✓ Connection successful![/bold green]")

    # Step 3: Storage
    console.print()
    console.print(Panel(
        "[bold]Step 3/3: Saving Your Key[/bold]\n\n"
        "Your API key will be securely stored in your system keychain.\n"
        "[dim](Same secure storage used for your passwords)[/dim]",
        title="💾 Secure Storage",
        border_style="green",
    ))

    time.sleep(0.5)
    console.print("\n[bold green]✓ API key securely saved to system keychain.[/bold green]")

    # Success
    console.print()
    console.print(Panel(
        "[bold green]✅ All Set![/bold green]\n\n"
        "Your FrenchVocab is ready to use!\n\n"
        "🎯 Provider: [bold]Google Gemini[/bold]\n"
        "🔐 Storage: [bold]System Keychain[/bold]\n"
        "📚 You can now add vocabulary and translate!\n\n"
        "[dim]Tip: Your key is saved - you won't need to enter it again.[/dim]",
        title="🎉 Setup Complete",
        border_style="green",
    ))


def demo_comparison():
    """Show before/after comparison."""
    console.print("\n" + "="*70)
    console.print("[bold cyan]COMPARISON: OLD vs NEW ONBOARDING[/bold cyan]")
    console.print("="*70 + "\n")

    console.print("[bold red]❌ OLD EXPERIENCE (Overwhelming):[/bold red]\n")
    console.print("1. User runs app")
    console.print("2. Prompted: 'Choose provider: 1) Gemini 2) Claude'")
    console.print("   → User confused: 'Which one is better?'")
    console.print("3. Prompted: 'Paste your API key'")
    console.print("   → User lost: 'Where do I get one?'")
    console.print("4. Prompted: 'Storage: 1) Keyring 2) .env 3) Session'")
    console.print("   → User overwhelmed: 'What's keyring? What should I pick?'")
    console.print("5. Success, but user is exhausted")

    console.print("\n[bold green]✅ NEW EXPERIENCE (Guided):[/bold green]\n")
    console.print("1. User runs app")
    console.print("2. Choice: 'Guided Setup (Recommended)' or 'Advanced'")
    console.print("   → 90% choose Guided")
    console.print("3. Step 1: Clear instructions to get Gemini key (with URL)")
    console.print("4. Step 2: Paste key (with validation)")
    console.print("5. Step 3: Automatic keyring storage (no choice needed)")
    console.print("6. Success screen with clear confirmation")
    console.print("   → User feels confident and informed!")

    console.print("\n[bold yellow]KEY IMPROVEMENTS:[/bold yellow]")
    console.print("• ✨ Opinionated defaults (Gemini, keyring)")
    console.print("• 📝 Step-by-step guidance with URLs")
    console.print("• 🎯 No decision fatigue (3 steps vs 6 decisions)")
    console.print("• 🔒 Secure by default (keyring auto-selected)")
    console.print("• 🚀 Advanced mode still available for power users")


if __name__ == "__main__":
    console.print("\n[bold]🎬 DEMO: New Guided Onboarding Flow[/bold]\n")

    import sys
    if "--comparison" in sys.argv:
        demo_comparison()
    else:
        demo_guided_flow()
        console.print("\n[dim]Run with --comparison to see before/after comparison[/dim]\n")
