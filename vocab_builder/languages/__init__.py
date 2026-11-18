from __future__ import annotations

from typing import Dict, List

from .base import (
    LanguageConfig,
    CompositionConfig,
    TranslatorConfig,
    AnkiConfig,
    AnkiCardTemplate,
    VocabTemplate,
    InputValidator,
    LearningMode,
)

# Lazy loading for language configs - only load when actually needed
_CONFIGS: Dict[str, LanguageConfig] = {}
_ALIASES: Dict[str, str] = {}
_DEFAULT_LANGUAGE_CODE = "fr"
_configs_loaded = False


def _ensure_configs_loaded() -> None:
    """Load the bundled language configs on first use."""
    global _configs_loaded
    if _configs_loaded:
        return

    from .english import ENGLISH_CONFIG
    from .french import FRENCH_CONFIG
    from .german import GERMAN_CONFIG

    for config in (ENGLISH_CONFIG, FRENCH_CONFIG, GERMAN_CONFIG):
        _CONFIGS[config.code] = config
        for alias in config.aliases:
            _ALIASES[alias] = config.code

    _configs_loaded = True


def get_language_config(language: str | None) -> LanguageConfig:
    """Resolve a language code or alias to a LanguageConfig."""
    _ensure_configs_loaded()
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
    _ensure_configs_loaded()
    return sorted(_CONFIGS.keys())


def default_language_code() -> str:
    return _DEFAULT_LANGUAGE_CODE


__all__ = [
    "LanguageConfig",
    "CompositionConfig",
    "TranslatorConfig",
    "AnkiConfig",
    "AnkiCardTemplate",
    "VocabTemplate",
    "InputValidator",
    "LearningMode",
    "get_language_config",
    "available_language_codes",
    "default_language_code",
]
