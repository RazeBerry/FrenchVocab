"""Menu orchestration helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from core.protocols import VocabAppProtocol


def main_menu_loop(app: "VocabAppProtocol") -> None:
    """Interactive menu loop driving the CLI session."""
    app.welcome_screen()
    while True:
        _refresh_menu_counts(app)

        choice = app.show_menu()

        if not _handle_main_choice(app, choice):
            break


def _refresh_menu_counts(app: "VocabAppProtocol") -> None:
    app.entry_count = app.count_entries()
    if app.eng_to_fr_translator:
        app.eng_to_fr_translator.entry_count = len(app.eng_to_fr_translator.pairs)
    if app.fr_to_eng_translator:
        app.fr_to_eng_translator.entry_count = len(app.fr_to_eng_translator.pairs)


def _handle_main_choice(app: "VocabAppProtocol", choice: str) -> bool:
    if choice == "add":
        app.handle_new_word_entry()
        return True

    if choice == "translate":
        _handle_translation(app)
        return True

    if choice == "anki_tools":
        app.handle_anki_tools()
        return True

    if choice == "display_vocab":
        app.display_all_vocabulary()
        return True

    if choice == "settings":
        app.show_settings_screen()
        return True

    if choice == "exit":
        app.exit_screen()
        return False

    app.ui.warning("Unrecognized menu option. Please try again.")
    return True


def _handle_translation(app: "VocabAppProtocol") -> None:
    translation_choice = app.show_translation_menu()
    handlers = {
        "auto": _run_auto_translation,
        "eng_to_target": _run_eng_to_target,
        "target_to_eng": _run_target_to_eng,
    }
    handler = handlers.get(translation_choice)
    if handler:
        handler(app)


def _run_auto_translation(app: "VocabAppProtocol") -> None:
    if not app.ensure_llm_ready():
        return
    if app.auto_translator:
        app.auto_translator.run()
        return
    app.ui.error("Auto translator is unavailable because the AI provider could not be initialized.")


def _run_eng_to_target(app: "VocabAppProtocol") -> None:
    if not app.ensure_llm_ready():
        return
    if app.eng_to_fr_translator:
        app.eng_to_fr_translator.run()
        return
    title = app._translator_title(app.language_config.eng_to_target)
    app.ui.error(f"{title} is unavailable because the AI provider could not be initialized.")


def _run_target_to_eng(app: "VocabAppProtocol") -> None:
    if not app.ensure_llm_ready():
        return
    if app.fr_to_eng_translator:
        app.fr_to_eng_translator.run()
        return
    title = app._translator_title(app.language_config.target_to_eng)
    app.ui.error(f"{title} is unavailable because the AI provider could not be initialized.")
