"""Protocol interfaces for core components.

This module defines structural typing contracts (Protocols) to:
1. Keep menu orchestration decoupled from concrete app classes
2. Enable duck typing for test doubles
3. Document the public interface contract
"""

from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from core.translator import TranslatorCLI
    from core.auto_translator import AutoTranslator
    from languages.base import LanguageConfig, TranslatorConfig
    from ui_helper import UIHelper


class VocabAppProtocol(Protocol):
    """Contract that menu orchestration depends on.

    This Protocol defines the minimal interface required by
    ``core.menu_loop.main_menu_loop()`` and related helpers.
    FrenchVocabBuilder implements this protocol implicitly through structural
    subtyping.

    Using a Protocol:
    - Keeps menu loop helpers independent from the concrete builder class
    - Enables testing with lightweight mock objects
    - Documents the public API surface for menu orchestration
    """

    # -------------------------------------------------------------------------
    # Properties required by menu orchestration
    # -------------------------------------------------------------------------

    @property
    def entry_count(self) -> int:
        """Number of vocabulary entries in the LaTeX file."""
        ...

    @entry_count.setter
    def entry_count(self, value: int) -> None:
        ...

    @property
    def ui(self) -> "UIHelper":
        """UI helper for user interaction."""
        ...

    @property
    def language_config(self) -> "LanguageConfig":
        """Active language configuration."""
        ...

    @property
    def eng_to_fr_translator(self) -> Optional["TranslatorCLI"]:
        """English to target language translator, if available."""
        ...

    @property
    def fr_to_eng_translator(self) -> Optional["TranslatorCLI"]:
        """Target language to English translator, if available."""
        ...

    @property
    def auto_translator(self) -> Optional["AutoTranslator"]:
        """Intelligent auto-routing translator, if available."""
        ...

    # -------------------------------------------------------------------------
    # Methods required by menu orchestration
    # -------------------------------------------------------------------------

    def welcome_screen(self) -> None:
        """Display the welcome screen with app status."""
        ...

    def show_menu(self) -> str:
        """Display the main menu and return the user's choice."""
        ...

    def show_translation_menu(self) -> str:
        """Display the translation submenu and return the user's choice."""
        ...

    def handle_new_word_entry(self) -> None:
        """Handle the flow for adding a new vocabulary word."""
        ...

    def ensure_llm_ready(self) -> bool:
        """Ensure LLM is available, prompting for setup if needed.

        Returns:
            True if LLM is ready for use, False otherwise.
        """
        ...

    def handle_anki_tools(self) -> bool:
        """Handle the Anki export tools submenu.

        Returns:
            True to stay in submenu, False to return to main menu.
        """
        ...

    def display_all_vocabulary(self) -> None:
        """Display all vocabulary entries to the user."""
        ...

    def show_settings_screen(self) -> None:
        """Display the settings/configuration screen."""
        ...

    def exit_screen(self) -> None:
        """Display the exit screen with session summary."""
        ...

    def count_entries(self) -> int:
        """Count the number of vocabulary entries.

        Returns:
            The current entry count.
        """
        ...

    def _translator_title(self, config: "TranslatorConfig") -> str:
        """Generate a display title for a translator configuration.

        Args:
            config: The translator configuration.

        Returns:
            Human-readable title string.
        """
        ...
