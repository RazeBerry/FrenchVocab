"""Menu orchestration helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from core.protocols import VocabAppProtocol


def main_menu_loop(app: "VocabAppProtocol") -> None:
    """Interactive menu loop driving the CLI session."""
    app.welcome_screen()
    while True:
        app.entry_count = app.count_entries()
        if app.eng_to_fr_translator:
            app.eng_to_fr_translator.entry_count = len(app.eng_to_fr_translator.pairs)
        if app.fr_to_eng_translator:
            app.fr_to_eng_translator.entry_count = len(app.fr_to_eng_translator.pairs)

        choice = app.show_menu()

        if choice == "add":
            app.handle_new_word_entry()
            continue

        if choice == "translate":
            translation_choice = app.show_translation_menu()
            if translation_choice == "auto":
                if not app.ensure_llm_ready():
                    continue
                if app.auto_translator:
                    app.auto_translator.run()
                else:
                    app.ui.error("Auto translator is unavailable because the AI provider could not be initialized.")
                continue
            if translation_choice == "eng_to_target":
                if not app.ensure_llm_ready():
                    continue
                if app.eng_to_fr_translator:
                    app.eng_to_fr_translator.run()
                else:
                    title = app._translator_title(app.language_config.eng_to_target)
                    app.ui.error(f"{title} is unavailable because the AI provider could not be initialized.")
                continue

            if translation_choice == "target_to_eng":
                if not app.ensure_llm_ready():
                    continue
                if app.fr_to_eng_translator:
                    app.fr_to_eng_translator.run()
                else:
                    title = app._translator_title(app.language_config.target_to_eng)
                    app.ui.error(f"{title} is unavailable because the AI provider could not be initialized.")
                continue

            continue  # translation menu returned "back"

        if choice == "anki_tools":
            app.handle_anki_tools()
            continue

        if choice == "display_vocab":
            app.display_all_vocabulary()
            continue

        if choice == "settings":
            app.show_settings_screen()
            continue

        if choice == "exit":
            app.exit_screen()
            break

        app.ui.warning("Unrecognized menu option. Please try again.")
