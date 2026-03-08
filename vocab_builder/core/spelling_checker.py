"""Spelling correction from AI responses.

This module handles extracting spelling suggestions from AI responses
and prompting users to accept or reject corrections.
"""

import re
import string
from typing import Optional

from vocab_builder.ui_helper import UIHelper


class SpellingChecker:
    """Handles spelling correction from AI responses."""

    def __init__(self, ui: UIHelper):
        self.ui = ui

    def check(self, original_word: str, ai_response: str) -> Optional[str]:
        """
        Extract spelling suggestion from AI response and prompt user.

        Args:
            original_word: The word as entered by the user.
            ai_response: The full AI response containing spelling check section.

        Returns:
            - The corrected spelling if user accepts
            - The original word if user rejects or no correction needed
            - None if user abandons the entry entirely
        """
        corrected_spelling = self._extract_suggestion(ai_response)

        if not corrected_spelling:
            return original_word

        # Validate the corrected spelling - check if it's empty, placeholder text, or same as input
        if self._is_placeholder(corrected_spelling, original_word):
            return original_word

        trimmed_original = original_word.strip()
        trimmed_corrected = corrected_spelling.strip()

        normalized_original = self._strip_trailing_punctuation(trimmed_original)
        normalized_corrected = self._strip_trailing_punctuation(trimmed_corrected)

        if normalized_original.lower() == normalized_corrected.lower():
            # Case-only or trailing punctuation differences - trust cleaned suggestion silently
            return normalized_corrected or corrected_spelling

        # Valid correction found that's different from input - ASK IMMEDIATELY
        return self._prompt_correction(original_word, corrected_spelling)

    def _extract_suggestion(self, ai_response: str) -> Optional[str]:
        """Extract the 'Correctly Spelt Word' from AI response."""
        # More specific regex that stops at the next field and handles multiline content
        corrected_spelling_match = re.search(
            r'Correctly Spelt Word:\s*(.*?)(?=\nWord Type:|$)',
            ai_response,
            re.DOTALL
        )
        if corrected_spelling_match:
            return corrected_spelling_match.group(1).strip()
        return None

    def _is_placeholder(self, corrected: str, original: str) -> bool:
        """Check if the correction is a placeholder or effectively the same as input."""
        # Remove common placeholder patterns
        if (corrected.startswith('[') and corrected.endswith(']')):
            return True
        if not corrected.strip():
            return True
        if corrected.lower().strip() == original.lower().strip():
            return True
        return False

    def _strip_trailing_punctuation(self, text: str) -> str:
        """Normalize by removing trailing punctuation and surrounding whitespace."""
        if not text:
            return text
        return text.rstrip(string.punctuation + " \t\r\n")

    def _prompt_correction(self, original: str, suggestion: str) -> Optional[str]:
        """Display spelling suggestion and prompt user for decision."""
        suggestion_panel = (
            "[bold]You entered:[/bold] "
            f"[bold red]{original}[/bold red]\n"
            "[bold]Suggested spelling:[/bold] "
            f"[bold green]{suggestion}[/bold green]"
        )
        self.ui.panel(
            suggestion_panel,
            title="Spelling Suggestion",
            border_style="yellow",
        )

        # Ask user to choose immediately (before generating LaTeX)
        use_corrected = self.ui.confirm(
            f"Use corrected spelling '{suggestion}'?",
            default=True,
        )

        if use_corrected:
            self.ui.info(f"Using corrected spelling: '{suggestion}'")
            return suggestion
        else:
            self.ui.info(f"Keeping original spelling: '{original}'")
            return original
