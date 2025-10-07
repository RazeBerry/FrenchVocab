from __future__ import annotations

from typing import Dict, List

from .base import (
    LanguageConfig,
    TranslatorConfig,
    AnkiConfig,
    AnkiCardTemplate,
    VocabTemplate,
    InputValidator,
)
from .french import FRENCH_CONFIG
from .german import GERMAN_CONFIG

_CONFIGS: Dict[str, LanguageConfig] = {
    FRENCH_CONFIG.code: FRENCH_CONFIG,
    GERMAN_CONFIG.code: GERMAN_CONFIG,
}
_ALIASES: Dict[str, str] = {alias: FRENCH_CONFIG.code for alias in FRENCH_CONFIG.aliases}
_ALIASES.update({alias: GERMAN_CONFIG.code for alias in GERMAN_CONFIG.aliases})
_DEFAULT_LANGUAGE_CODE = FRENCH_CONFIG.code


def register_language(config: LanguageConfig) -> None:
    """Register a new language configuration."""
    _CONFIGS[config.code] = config
    for alias in config.aliases:
        _ALIASES[alias] = config.code


def get_language_config(language: str | None) -> LanguageConfig:
    """Resolve a language code or alias to a LanguageConfig."""
    if not language:
        return _CONFIGS[_DEFAULT_LANGUAGE_CODE]

    key = language.lower()
    if key in _CONFIGS:
        return _CONFIGS[key]

    canonical = _ALIASES.get(key)
    if canonical and canonical in _CONFIGS:
        return _CONFIGS[canonical]

    raise ValueError(f"Unsupported language code '{language}'. Available: {', '.join(available_language_codes())}")


def available_language_codes() -> List[str]:
    """List canonical language codes in alphabetical order."""
    return sorted(_CONFIGS.keys())


def default_language_code() -> str:
    return _DEFAULT_LANGUAGE_CODE


__all__ = [
    "LanguageConfig",
    "TranslatorConfig",
    "AnkiConfig",
    "AnkiCardTemplate",
    "VocabTemplate",
    "InputValidator",
    "register_language",
    "get_language_config",
    "available_language_codes",
    "default_language_code",
]
