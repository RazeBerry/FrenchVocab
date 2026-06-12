"""Backward-compatibility helpers for the FrenchVocab -> VocabBuilder rename.

This module provides dual-read wrappers for environment variables, config
directories, and keyring service names so existing users are not broken by
the rename.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Environment variable mapping: new name → old name(s)
# ---------------------------------------------------------------------------

_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    # FRENCHVOCAB_ prefix
    "VOCABBUILDER_ESC_DEBUG": ("FRENCHVOCAB_ESC_DEBUG",),
    "VOCABBUILDER_ESC_DEBUG_LOG": ("FRENCHVOCAB_ESC_DEBUG_LOG",),
    "VOCABBUILDER_ESC_SEQUENCE_TIMEOUT": ("FRENCHVOCAB_ESC_SEQUENCE_TIMEOUT",),
    "VOCABBUILDER_CONFIG_DIR": ("FRENCHVOCAB_CONFIG_DIR",),
    "VOCABBUILDER_SKIP_KEYRING": ("FRENCHVOCAB_SKIP_KEYRING",),
    "VOCABBUILDER_FORCE_SYNC_LOAD": ("FRENCHVOCAB_FORCE_SYNC_LOAD",),
    "VOCABBUILDER_DEBUG_EXPORT": ("FRENCHVOCAB_DEBUG_EXPORT",),
    "VOCABBUILDER_TEST_PROVIDER_AUTODETECT": ("FRENCHVOCAB_TEST_PROVIDER_AUTODETECT",),
    "VOCABBUILDER_MAX_BACKUPS": ("FRENCHVOCAB_MAX_BACKUPS", "FRENCH_VOCAB_MAX_BACKUPS"),
    # FRENCH_VOCAB_ prefix
    "VOCABBUILDER_AUTO_TRANSLATOR": ("FRENCH_VOCAB_AUTO_TRANSLATOR",),
    "VOCABBUILDER_MAX_CHARS": ("FRENCH_VOCAB_MAX_CHARS",),
    "VOCABBUILDER_MAX_WORDS": ("FRENCH_VOCAB_MAX_WORDS",),
    "VOCABBUILDER_SENTENCE_MODE": ("FRENCH_VOCAB_SENTENCE_MODE",),
    "VOCABBUILDER_ALLOW_PUNCT": ("FRENCH_VOCAB_ALLOW_PUNCT",),
    "VOCABBUILDER_ROUTE_SENTENCES": ("FRENCH_VOCAB_ROUTE_SENTENCES",),
    "VOCABBUILDER_SENTENCE_EXAMPLES": ("FRENCH_VOCAB_SENTENCE_EXAMPLES",),
    "VOCABBUILDER_HISTORY_DISABLED": ("FRENCH_VOCAB_HISTORY_DISABLED",),
    "VOCABBUILDER_HISTORY_ENABLED": ("FRENCH_VOCAB_HISTORY_ENABLED",),
    "VOCABBUILDER_HISTORY_DIR": ("FRENCH_VOCAB_HISTORY_DIR",),
}


def get_env(new_name: str, default: Optional[str] = None) -> Optional[str]:
    """Read an env var by its new VOCABBUILDER_* name, falling back to legacy names.

    When a legacy name is found but the new name is not set, a
    ``DeprecationWarning`` is emitted once per variable name.
    """
    value = os.environ.get(new_name)
    if value is not None:
        return value

    old_names = _ENV_ALIASES.get(new_name, ())
    for old_name in old_names:
        old_value = os.environ.get(old_name)
        if old_value is not None:
            warnings.warn(
                f"Environment variable {old_name} is deprecated; use {new_name} instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return old_value

    return default


# ---------------------------------------------------------------------------
# Config directory
# ---------------------------------------------------------------------------

_NEW_CONFIG_DIR_NAME = ".vocabbuilder"
_OLD_CONFIG_DIR_NAME = ".frenchvocab"


def _dedupe_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return tuple(deduped)


def _explicit_config_home() -> Optional[Path]:
    raw = get_env("VOCABBUILDER_CONFIG_DIR")
    if not raw:
        return None
    return Path(raw).expanduser()


def config_home(*, create: bool = False, warn_on_legacy: bool = True) -> Path:
    """Return the preferred writable config directory.

    Preference order:
    1. ``VOCABBUILDER_CONFIG_DIR`` / legacy alias when set
    2. ``~/.vocabbuilder/`` for all default writes

    Legacy ``~/.frenchvocab/`` remains part of the read path via
    :func:`config_homes_for_read`, but new state is written to the new
    directory so the renamed app does not keep extending the deprecated path.
    """
    explicit = _explicit_config_home()
    if explicit is not None:
        if create:
            explicit.mkdir(parents=True, exist_ok=True)
        return explicit

    new_dir = Path.home() / _NEW_CONFIG_DIR_NAME
    old_dir = Path.home() / _OLD_CONFIG_DIR_NAME
    if old_dir.is_dir() and warn_on_legacy:
        warnings.warn(
            f"Config directory {old_dir} is deprecated; new state is written to {new_dir}.",
            DeprecationWarning,
            stacklevel=2,
        )

    if create:
        new_dir.mkdir(parents=True, exist_ok=True)

    if new_dir.is_dir():
        return new_dir

    return new_dir


def config_homes_for_read() -> tuple[Path, ...]:
    """Return config directories to consult when reading persisted user state."""
    explicit = _explicit_config_home()
    if explicit is not None:
        return (explicit,)

    new_dir = Path.home() / _NEW_CONFIG_DIR_NAME
    old_dir = Path.home() / _OLD_CONFIG_DIR_NAME
    candidates = [new_dir]
    if old_dir.is_dir():
        candidates.append(old_dir)
    return _dedupe_paths(candidates)


def runtime_root(source_root: Optional[Path] = None, *, create: bool = False) -> Path:
    """Return the writable root for mutable runtime files.

    A writable git checkout continues to use its repository root so existing
    source-based users keep their current files. Installed wheels fall back to
    the user config directory instead of writing into ``site-packages``.
    """
    explicit = _explicit_config_home()
    if explicit is not None:
        if create:
            explicit.mkdir(parents=True, exist_ok=True)
        return explicit

    if source_root is not None:
        root = Path(source_root).expanduser().resolve()
        if (root / ".git").exists() and os.access(root, os.W_OK):
            return root

    return config_home(create=create)


# ---------------------------------------------------------------------------
# Keyring service
# ---------------------------------------------------------------------------

_NEW_KEYRING_SERVICE = "vocab_builder"
_OLD_KEYRING_SERVICE = "french_vocab_builder"


def keyring_get_with_fallback(name: str) -> tuple[Optional[str], str]:
    """Look up a keyring credential under the new service, falling back to old.

    Returns:
        (value, service_name) — the value found (or None) and which service it came from.
    """
    import keyring  # type: ignore[import]

    value = keyring.get_password(_NEW_KEYRING_SERVICE, name)
    if value is not None:
        return value, _NEW_KEYRING_SERVICE

    old_value = keyring.get_password(_OLD_KEYRING_SERVICE, name)
    if old_value is not None:
        # Silently migrate to new service
        try:
            keyring.set_password(_NEW_KEYRING_SERVICE, name, old_value)
        except Exception:
            pass  # Migration is best-effort
        return old_value, _OLD_KEYRING_SERVICE

    return None, _NEW_KEYRING_SERVICE


def keyring_set(name: str, value: str) -> None:
    """Store a credential under the new keyring service name."""
    import keyring  # type: ignore[import]

    keyring.set_password(_NEW_KEYRING_SERVICE, name, value)


KEYRING_SERVICE = _NEW_KEYRING_SERVICE
