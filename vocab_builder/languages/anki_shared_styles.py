"""Shared Anki card styles for all language configurations."""

from __future__ import annotations

from string import Template
from typing import Callable

from .base import AnkiCardTemplate

BASE_ANKI_CARD_CSS = """
.card {
    font-family: 'Palatino Linotype', 'Palatino', 'Book Antiqua', Georgia, Cambria, serif;
    font-size: 12pt;
    color: var(--card-fg, #1f1f1f);
    background-color: transparent;
    line-height: 1.48;
    padding: 26px 28px;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

.nightMode .card,
body.nightMode .card,
body.night_mode .card {
    color: var(--night-card-fg, #f6f2ed);
}

.entry-card {
    max-width: 680px;
    margin: 0 auto;
    text-align: left;
}

.entry-header {
    border-bottom: 1px solid currentColor;
    padding-bottom: 0.6em;
    margin-bottom: 1.2em;
}

.entry-word {
    font-size: 1.6em;
    font-weight: 600;
    letter-spacing: 0.03em;
}

.entry-pos {
    font-variant: small-caps;
    letter-spacing: 0.12em;
    font-size: 0.72em;
    margin-top: 0.4em;
    color: inherit;
    opacity: 0.75;
}

.entry-section {
    margin-bottom: 1.15em;
}

.entry-section-title {
    font-variant: small-caps;
    letter-spacing: 0.12em;
    font-size: 0.9em;
    margin-bottom: 0.35em;
    color: inherit;
    opacity: 0.75;
}

.entry-content {
    color: inherit;
}

.entry-list {
    margin: 0;
    padding-left: 1.5em;
}

.entry-list li {
    margin-bottom: 0.35em;
}

.entry-list li::marker {
    color: currentColor;
}

.entry-card--front {
    min-height: 180px;
    display: flex;
    flex-direction: column;
    justify-content: center;
}

.entry-card--back .entry-section:last-child {
    margin-bottom: 0;
}

/* Responsive Design - Mobile */
@media (max-width: 640px) {
    .card {
        font-size: 11pt;
        padding: 20px 18px;
    }

    .entry-word {
        font-size: 1.5em;
    }

    .entry-card--front {
        min-height: 140px;
    }
}

/* Responsive Design - Small Mobile */
@media (max-width: 480px) {
    .card {
        font-size: 10.5pt;
        padding: 16px 14px;
    }

    .entry-word {
        font-size: 1.45em;
    }

    .entry-pos {
        font-size: 0.68em;
    }
}

/* Accessibility - Reduced Motion */
@media (prefers-reduced-motion: reduce) {
    * {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}

/* Print Styles */
@media print {
    .card {
        background-color: white;
        color: #000;
        padding: 12px;
        font-size: 12pt;
    }

    .entry-header {
        border-bottom: 1pt solid currentColor;
    }
}
""".strip()


def _load_theme_override() -> Callable[[str], str]:
    """Return a best-effort accessor for optional theme overrides."""
    try:
        from .anki_themes import get_theme_css

        return get_theme_css
    except Exception:  # pragma: no cover - optional dependency
        return lambda _language_code: ""


def get_anki_css(language_code: str = "default") -> str:
    """Return the base Anki CSS with optional theme overrides applied."""
    theme_resolver = _load_theme_override()
    theme_css = theme_resolver(language_code)
    if theme_css:
        return f"{BASE_ANKI_CARD_CSS}\n\n{theme_css.strip()}"
    return BASE_ANKI_CARD_CSS


# The bilingual recognition card. ``$headword`` is the Anki field holding the
# target-language headword; Anki's double braces escape HTML, and the exporter
# supplies plain-text lists for the definition and example fields.
_BILINGUAL_FRONT = Template("""
<div class="entry-card entry-card--front">
  <div class="entry-header">
    <div class="entry-word">{{$headword}}</div>
    {{#Type}}<div class="entry-pos">{{Type}}</div>{{/Type}}
  </div>
</div>
""".strip())

_BILINGUAL_BACK = Template("""
<div class="entry-card entry-card--back">
  <div class="entry-header">
    <div class="entry-word">{{$headword}}</div>
    {{#Type}}<div class="entry-pos">{{Type}}</div>{{/Type}}
  </div>
  {{#English}}
  <div class="entry-section">
    <div class="entry-section-title">Definitions</div>
    <div class="entry-content">{{English}}</div>
  </div>
  {{/English}}
  {{#Example}}
  <div class="entry-section">
    <div class="entry-section-title">Examples</div>
    <div class="entry-content">{{Example}}</div>
  </div>
  {{/Example}}
</div>
""".strip())


def bilingual_card_templates(headword_field: str) -> tuple[AnkiCardTemplate, ...]:
    """Return the bilingual card whose headword lives in ``headword_field``.

    The note fields are ``(headword_field, "Type", "English", "Example")``.
    """
    return (
        AnkiCardTemplate(
            name="Card 1",
            question_format=_BILINGUAL_FRONT.substitute(headword=headword_field),
            answer_format=_BILINGUAL_BACK.substitute(headword=headword_field),
        ),
    )


__all__ = [
    "BASE_ANKI_CARD_CSS",
    "bilingual_card_templates",
    "get_anki_css",
]
