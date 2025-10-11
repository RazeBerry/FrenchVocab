"""Menu orchestration helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from core import FrenchVocabBuilder


def main_menu_loop(app: "FrenchVocabBuilder") -> None:
    """Interactive menu loop driving the CLI session."""
    app.welcome_screen()
    while True:
        app.entry_count = app.count_entries()
        if app.eng_to_fr_translator:
            app.eng_to_fr_translator.entry_count = len(app.eng_to_fr_translator.pairs)
        if app.fr_to_eng_translator:
            app.fr_to_eng_translator.entry_count = len(app.fr_to_eng_translator.pairs)

        choice = app.show_menu()
        pause_required = True

        if choice == "add":
            app.handle_new_word_entry()
        elif choice == "eng_to_target":
            if app.eng_to_fr_translator:
                app.eng_to_fr_translator.run()
            else:
                title = app._translator_title(app.language_config.eng_to_target)
                app.ui.error(f"{title} is not available (initialization failed).")
        elif choice == "target_to_eng":
            if app.fr_to_eng_translator:
                app.fr_to_eng_translator.run()
            else:
                title = app._translator_title(app.language_config.target_to_eng)
                app.ui.error(f"{title} is not available (initialization failed).")
        elif choice == "anki_tools":
            pause_required = app.handle_anki_tools()
        elif choice == "display_vocab":
            app.display_all_vocabulary()
        elif choice == "exit":
            app.exit_screen()
            pause_required = False
            break
        else:
            app.ui.warning("Unrecognized menu option. Please try again.")
            pause_required = False

        if pause_required:
            input("\nPress Enter to continue...")
