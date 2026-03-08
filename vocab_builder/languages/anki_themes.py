"""Optional language-specific Anki card theme overrides."""

from __future__ import annotations

from typing import Dict

THEME_OVERRIDES: Dict[str, str] = {
    # Example overrides to illustrate future theming capabilities.
    "fr": """
/* French-specific overrides */
.entry-content q {
    quotes: "«\\00A0" "\\00A0»" "‹\\00A0" "\\00A0›";
}
""",
    "de": """
/* German-specific overrides */
.entry-word {
    font-weight: 650;
}
""",
}


def get_theme_css(language_code: str) -> str:
    """Return optional theme-specific CSS for the provided language code."""
    return THEME_OVERRIDES.get(language_code, "")


__all__ = ["THEME_OVERRIDES", "get_theme_css"]
