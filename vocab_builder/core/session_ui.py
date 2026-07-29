"""UI/session flow helpers for the main vocabulary app controller."""

from __future__ import annotations

from typing import Any, Optional, Tuple


def _translation_pair_count(
    app: Any,
    *,
    translator_attr: str,
    file_attr: str,
    config: Any,
) -> int:
    if config is None:
        return 0
    translator = getattr(app, translator_attr, None)
    if translator is not None:
        return translator.entry_count

    latex_file = getattr(app, file_attr, None)
    commands = tuple(getattr(config, "latex_commands", ()) or ())
    if latex_file is None or not commands:
        return 0
    return _count_translation_pairs_on_disk(latex_file, commands)


def _count_translation_pairs_on_disk(latex_file: Any, commands: Tuple[str, ...]) -> int:
    from pathlib import Path

    from vocab_builder.latex_repository import iter_entry_groups

    path = Path(latex_file)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0

    count = 0
    for command in commands:
        entry_cmd = command if command.startswith("\\") else f"\\{command}"
        for _groups, start, _end in iter_entry_groups(content, entry_cmd, num_groups=2):
            if not _command_is_in_latex_comment(content, start):
                count += 1
    return count


def _command_is_in_latex_comment(content: str, command_pos: int) -> bool:
    line_start = content.rfind("\n", 0, command_pos) + 1
    prefix = content[line_start:command_pos]
    for index, char in enumerate(prefix):
        if char != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and prefix[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return True
    return False


def _composition_debt_count(app: Any) -> Optional[int]:
    if not getattr(app, "enable_composition", True):
        return None
    getter = getattr(app, "composition_debt_count", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except (OSError, RuntimeError, ValueError, AttributeError):
        return None


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
        f"[italic cyan]Version 3.0[/italic cyan]\n"
        "[dim]CLI: vocabbuilder | Module: python -m vocab_builder[/dim]"
    )
    return message, panel_title


def refresh_anki_snapshot_on_exit(app: Any) -> Optional[str]:
    """Refresh the complete Anki package without blocking a clean exit."""
    from vocab_builder.core.anki_manager import AnkiSnapshotStatus, exit_snapshot_enabled

    if not exit_snapshot_enabled():
        return None

    try:
        result = app._ensure_anki_manager().export_snapshot_if_changed(
            export_context="clean_exit",
            quiet=True,
        )
    except Exception as exc:
        app.ui.warning(
            "Could not refresh the Anki snapshot on exit; "
            f"your vocabulary remains safely stored in LaTeX ({exc})."
        )
        return None

    if result.status == AnkiSnapshotStatus.FAILED:
        app.ui.warning(
            "Could not refresh the Anki snapshot on exit; "
            "your vocabulary remains safely stored in LaTeX."
        )
        return None
    if result.status == AnkiSnapshotStatus.EXPORTED and result.path is not None:
        return str(result.path)
    return None


def show_main_menu(app: Any) -> str:
    supports_translation = app.language_config.supports_translation
    eng_fr_count = 0
    fr_eng_count = 0
    if supports_translation:
        eng_fr_count = _translation_pair_count(
            app,
            translator_attr="eng_to_target_translator",
            file_attr="eng_to_target_latex_file",
            config=app.language_config.eng_to_target,
        )
        fr_eng_count = _translation_pair_count(
            app,
            translator_attr="target_to_eng_translator",
            file_attr="target_to_eng_latex_file",
            config=app.language_config.target_to_eng,
        )

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

    status_parts = [f"[bold]Library:[/bold] {app.entry_count} vocab words"]
    if supports_translation:
        total_translation_pairs = eng_fr_count + fr_eng_count
        status_parts.append(f"[bold]Translations:[/bold] {total_translation_pairs} pairs")
    status_parts.append(f"[bold]AI:[/bold] [{provider_color}]{provider_status}[/{provider_color}]")
    status_text = "  |  ".join(status_parts)
    app.ui.panel(status_text, title="Status", border_style="dim dark_orange")

    add_word_label = app._ui_text("menu.add_word", f"Add {language_name} word")
    composition_count = _composition_debt_count(app)

    options = [("add", add_word_label)]
    if supports_translation:
        options.append(("translate", "Translate text"))
    if composition_count is not None:
        options.append(("composition", f"Composition practice   ({composition_count} unproduced)"))
    options.extend(
        [
            ("anki_tools", "Anki tools"),
            ("browse", "Browse vocabulary"),
            ("settings", "Settings & Configuration"),
            ("exit", "[bold yellow]Exit[/bold yellow]"),
        ]
    )

    try:
        return app.ui.interactive_menu(
            "Main Menu",
            options,
            "[↑↓] Navigate • [Enter] Select • [Esc] Exit",
        )
    except KeyboardInterrupt:
        return "exit"


def show_translation_menu(app: Any) -> str:
    eng_to_cfg = app.language_config.eng_to_target
    target_to_cfg = app.language_config.target_to_eng
    if not app.language_config.supports_translation or not eng_to_cfg or not target_to_cfg:
        app.ui.warning("Translation tools are not used in monolingual vocabulary mode.")
        return "back"
    eng_fr_count = _translation_pair_count(
        app,
        translator_attr="eng_to_target_translator",
        file_attr="eng_to_target_latex_file",
        config=eng_to_cfg,
    )
    fr_eng_count = _translation_pair_count(
        app,
        translator_attr="target_to_eng_translator",
        file_attr="target_to_eng_latex_file",
        config=target_to_cfg,
    )

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
            elif translation_choice == "eng_to_target" and app.eng_to_target_translator:
                if app.ensure_llm_ready():
                    app.eng_to_target_translator.run()
            elif translation_choice == "target_to_eng" and app.target_to_eng_translator:
                if app.ensure_llm_ready():
                    app.target_to_eng_translator.run()
            return "translate"
        if quick_action == "add":
            return "add"
        return quick_action
    except KeyboardInterrupt:
        return None
