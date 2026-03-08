"""Shared ESC-key timing configuration."""

from __future__ import annotations

import os


def read_esc_sequence_timeout(default: float = 0.03) -> float:
    """Return a safe ESC sequence timeout from environment settings."""
    raw = os.environ.get("FRENCHVOCAB_ESC_SEQUENCE_TIMEOUT")
    if raw is None:
        return default

    value = raw.strip()
    if not value:
        return default

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default

    if parsed < 0:
        return default
    return parsed

