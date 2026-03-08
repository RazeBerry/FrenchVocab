"""UI/session flow helpers for the main vocabulary app controller."""

from __future__ import annotations

from typing import Any, Optional, Tuple


def resolve_welcome_provider_name(app: Any) -> str:
    from vocab_builder.core.llm_coordinator import InitState

    if app._llm.init_state == InitState.IN_PROGRESS:
        # Give background init a moment to settle so the welcome screen does not
        # get stuck showing "initializing" when no credentials are present.
        app._llm.await_init(timeout=0.2)
    state = app._llm.init_state

    provider_name = app.provider_metadata.display_name if hasattr(app, "provider_metadata") else "Unknown"
    client = app.client
    if client is not None:
        label_getter = getattr(client, "model_label", None)
        if callable(label_getter):
            try:
                provider_name = label_getter()
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                if app.verbose:
                    app.ui.debug(f"Failed to read model label from client: {exc}")
                provider_name = client.__class__.__name__
        else:
            model_name = getattr(client, "MODEL_NAME", None)
            if model_name:
                provider_name = f"Google Gemini ({model_name})"
    else:
        if state == InitState.IN_PROGRESS:
            provider_name = f"{provider_name} (initializing)"
        elif state == InitState.DEFERRED:
            provider_name = f"{provider_name} (init deferred)"
        else:
            provider_name = f"{provider_name} (not configured)"
    return provider_name


def build_welcome_message(app: Any, provider_name: str) -> Tuple[str, str]:
    language_name = app.language_config.display_name
    app_title = app._ui_text("app.title", f"{language_name} Vocabulary LaTeX Builder")
    panel_title = app._ui_text("app.panel_title", f"{language_name} Vocab Builder")
    message = (
        f"[bold #E67E50]Welcome to the {app_title}![/bold #E67E50]\n\n"
        f"This application helps you build a LaTeX document for {language_name} vocabulary.\n"
        f"You can input {language_name} words, and the AI will provide definitions and examples.\n\n"
        f"[bold green]Your current vocabulary library contains {app.entry_count} words.[/bold green]\n"
        f"[bold cyan]Using LLM provider: {provider_name}[/bold cyan]\n"
        f"[bold magenta]Active language: {language_name}[/bold magenta]\n\n"
        f"[italic cyan]Version 2.1[/italic cyan]\n"
        f"[dim]GitHub: https://github.com/RazeBerry/FrenchVocab/tree/main[/dim]"
    )
    return message, panel_title


def show_main_menu(app: Any) -> str:
    eng_fr_count = 0
    if app.eng_to_fr_translator:
        eng_fr_count = app.eng_to_fr_translator.entry_count

    fr_eng_count = 0
    if app.fr_to_eng_translator:
        fr_eng_count = app.fr_to_eng_translator.entry_count

    language_name = app.language_config.display_name

    # Display status summary panel above menu for reduced cognitive load.
    # Use the state machine for clean, unambiguous status.
    from vocab_builder.core.llm_coordinator import InitState

    if app._llm.init_state == InitState.IN_PROGRESS:
        app._llm.await_init(timeout=0.2)
    state = app._llm.init_state

    if state == InitState.READY:
        provider_status = "Connected"
        provider_color = "green"
    elif state == InitState.IN_PROGRESS:
        provider_status = "Initializing"
        provider_color = "yellow"
    elif state == InitState.DEFERRED:
        provider_status = "Deferred"
        provider_color = "yellow"
    else:  # FAILED or NOT_STARTED
        provider_status = "Unavailable"
        provider_color = "yellow"

    total_translation_pairs = eng_fr_count + fr_eng_count
    status_text = (
        f"[bold]Library:[/bold] {app.entry_count} vocab words  |  "
        f"[bold]Translations:[/bold] {total_translation_pairs} pairs  |  "
        f"[bold]AI:[/bold] [{provider_color}]{provider_status}[/{provider_color}]"
    )
    app.ui.panel(status_text, title="Status", border_style="dim dark_orange")

    add_word_label = app._ui_text("menu.add_word", f"Add {language_name} word")

    options = [
        ("add", add_word_label),
        ("translate", "Translate text"),
        ("anki_tools", "Anki tools"),
        ("browse", "Browse vocabulary"),
        ("settings", "Settings & Configuration"),
        ("exit", "[bold yellow]Exit[/bold yellow]"),
    ]

    try:
        return app.ui.interactive_menu(
            "Main Menu",
            options,
            "[↑↓] Navigate • [Enter] Select • [Esc] Exit",
        )
    except KeyboardInterrupt:
        return "exit"


def show_translation_menu(app: Any) -> str:
    eng_fr_count = 0
    if app.eng_to_fr_translator:
        eng_fr_count = app.eng_to_fr_translator.entry_count

    fr_eng_count = 0
    if app.fr_to_eng_translator:
        fr_eng_count = app.fr_to_eng_translator.entry_count

    eng_to_cfg = app.language_config.eng_to_target
    target_to_cfg = app.language_config.target_to_eng

    status_text = (
        f"[bold]{target_to_cfg.source_label} → {target_to_cfg.target_label}:[/bold] {fr_eng_count} pairs  |  "
        f"[bold]{eng_to_cfg.source_label} → {eng_to_cfg.target_label}:[/bold] {eng_fr_count} pairs"
    )
    app.ui.panel(status_text, title="Translation Status", border_style="dim dark_orange")

    options = []
    if app.auto_translator:
        options.append(("auto", f"Intelligent ({target_to_cfg.source_label} ↔ {eng_to_cfg.source_label})"))

    options.extend(
        [
            ("target_to_eng", f"{target_to_cfg.source_label} → {target_to_cfg.target_label}"),
            ("eng_to_target", f"{eng_to_cfg.source_label} → {eng_to_cfg.target_label}"),
            ("back", "Back to main menu"),
        ]
    )

    try:
        return app.ui.interactive_menu(
            "Translation Direction",
            options,
            "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            show_keys=False,
        )
    except KeyboardInterrupt:
        return "back"


def show_post_translation_menu(app: Any) -> Optional[str]:
    """Show quick actions after successful sentence translation."""
    try:
        quick_action = app.ui.interactive_menu(
            "What's next?",
            [
                ("translate", "Translate another sentence"),
                ("add", "Add a vocabulary word"),
                ("menu", "Return to main menu"),
            ],
            "Press Esc to return to main menu",
        )

        if quick_action == "translate":
            translation_choice = app.show_translation_menu()
            if translation_choice == "auto" and app.auto_translator:
                if app.ensure_llm_ready():
                    app.auto_translator.run()
            elif translation_choice == "eng_to_target" and app.eng_to_fr_translator:
                if app.ensure_llm_ready():
                    app.eng_to_fr_translator.run()
            elif translation_choice == "target_to_eng" and app.fr_to_eng_translator:
                if app.ensure_llm_ready():
                    app.fr_to_eng_translator.run()
            return "translate"
        if quick_action == "add":
            return "add"
        return quick_action
    except KeyboardInterrupt:
        return None
