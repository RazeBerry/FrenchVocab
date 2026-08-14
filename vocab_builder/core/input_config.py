"""Configuration for terminal input behavior."""

from __future__ import annotations

from vocab_builder.compat import get_env


_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on"})


def low_latency_input_requested() -> bool:
    """Return whether the CLI should avoid server-side per-key rendering.

    Canonical line input is intentionally less elaborate than the raw-key UI,
    but it turns a remote choice into one submitted line. That matters over SSH
    paths where each arrow, repaint, or prompt-toolkit refresh pays a network
    round trip.
    """
    raw = get_env("VOCABBUILDER_LOW_LATENCY_INPUT")
    return bool(raw and raw.strip().casefold() in _TRUE_VALUES)


def input_cancel_label() -> str:
    """Return the cancellation key advertised by the active input mode."""
    return "Ctrl+C" if low_latency_input_requested() else "Esc"


__all__ = ["input_cancel_label", "low_latency_input_requested"]
