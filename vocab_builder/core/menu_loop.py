"""Menu orchestration helpers used by the main application loop."""

from __future__ import annotations

from vocab_builder.core.protocols import VocabAppProtocol


def main_menu_loop(app: VocabAppProtocol) -> None:
    """Interactive menu loop driving the CLI session."""
    app.welcome_screen()
    while True:
        _refresh_menu_counts(app)

        choice = app.show_menu()

        if not _handle_main_choice(app, choice):
            break


def _refresh_menu_counts(app: VocabAppProtocol) -> None:
    app.entry_count = app.count_entries()
    if app.eng_to_target_translator:
        app.eng_to_target_translator.entry_count = len(app.eng_to_target_translator.pairs)
    if app.target_to_eng_translator:
        app.target_to_eng_translator.entry_count = len(app.target_to_eng_translator.pairs)


def _handle_main_choice(app: VocabAppProtocol, choice: str) -> bool:
    if choice == "exit":
        app.exit_screen()
        return False

    handlers = {
        "add": app.handle_new_word_entry,
        "translate": lambda: _handle_translation(app),
        "composition": app.handle_composition,
        "anki_tools": app.handle_anki_tools,
        "browse": app.browse_vocabulary,
        "settings": app.show_settings_screen,
    }
    handler = handlers.get(choice)
    if handler:
        handler()
        return True

    app.ui.warning("Unrecognized menu option. Please try again.")
    return True


def _handle_translation(app: VocabAppProtocol) -> None:
    translation_choice = app.show_translation_menu()
    handlers = {
        "auto": _run_auto_translation,
        "eng_to_target": _run_eng_to_target,
        "target_to_eng": _run_target_to_eng,
    }
    handler = handlers.get(translation_choice)
    if handler:
        handler(app)


def _run_auto_translation(app: VocabAppProtocol) -> None:
    if not app.ensure_llm_ready():
        return
    if app.auto_translator:
        app.auto_translator.run()
        return
    app.ui.error("Auto translator is unavailable because the AI provider could not be initialized.")


def _run_eng_to_target(app: VocabAppProtocol) -> None:
    if not app.ensure_llm_ready():
        return
    if app.eng_to_target_translator:
        app.eng_to_target_translator.run()
        return
    config = app.language_config.eng_to_target
    if config is None:
        app.ui.warning("Translation tools are unavailable in monolingual vocabulary mode.")
        return
    title = app._translator_title(config)
    app.ui.error(f"{title} is unavailable because the AI provider could not be initialized.")


def _run_target_to_eng(app: VocabAppProtocol) -> None:
    if not app.ensure_llm_ready():
        return
    if app.target_to_eng_translator:
        app.target_to_eng_translator.run()
        return
    config = app.language_config.target_to_eng
    if config is None:
        app.ui.warning("Translation tools are unavailable in monolingual vocabulary mode.")
        return
    title = app._translator_title(config)
    app.ui.error(f"{title} is unavailable because the AI provider could not be initialized.")
