"""
Ad-hoc ESC latency tracer.

When the environment variable ``FRENCHVOCAB_ESC_DEBUG`` is set to ``1``,
``true``, or ``on`` this module records prompt lifecycle events to a log file.
The destination defaults to ``~/.frenchvocab/esc_latency.log`` but can be
overridden with ``FRENCHVOCAB_ESC_DEBUG_LOG``.
"""

from __future__ import annotations

import datetime as _dt
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

_ENABLE_FLAG = os.environ.get("FRENCHVOCAB_ESC_DEBUG", "").strip().lower()
_ENABLED = _ENABLE_FLAG in {"1", "true", "on", "yes"}

def _default_log_path() -> Path:
    custom = os.environ.get("FRENCHVOCAB_ESC_DEBUG_LOG")
    if custom:
        return Path(custom).expanduser()
    root = Path.home() / ".frenchvocab"
    return root / "esc_latency.log"

_LOG_PATH = _default_log_path()
_LOCK = threading.Lock()


def _write_log_line(event: str, **payload: Any) -> None:
    if not _ENABLED:
        return
    timestamp = _dt.datetime.now().isoformat(timespec="milliseconds")
    parts = [f"{timestamp}", event]
    for key, value in payload.items():
        parts.append(f"{key}={value}")
    line = " ".join(parts)
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with _LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError:
        # Logging must not crash runtime; swallow errors silently.
        return


class _EscLatencyTracer:
    """Handles coarse timing for prompt lifecycle events."""

    def __init__(self) -> None:
        self._prompt_started_at: Optional[float] = None

    def mark_prompt_start(self, label: str) -> None:
        self._prompt_started_at = time.perf_counter()
        _write_log_line("prompt.start", label=repr(label))

    def mark_prompt_end(self, result: Any) -> None:
        elapsed_ms = None
        if self._prompt_started_at is not None:
            elapsed_ms = (time.perf_counter() - self._prompt_started_at) * 1000
        _write_log_line(
            "prompt.end",
            elapsed_ms=f"{elapsed_ms:.3f}" if elapsed_ms is not None else "unknown",
            result_repr=repr(result)[:40],
        )
        self._prompt_started_at = None

    def log_escape_handler(self, phase: str) -> None:
        elapsed_ms = None
        if self._prompt_started_at is not None:
            elapsed_ms = (time.perf_counter() - self._prompt_started_at) * 1000
        _write_log_line(
            "escape.handler",
            phase=phase,
            since_prompt_ms=f"{elapsed_ms:.3f}" if elapsed_ms is not None else "unknown",
        )

    def log_fallback(self, input_type: str) -> None:
        _write_log_line("input.fallback", channel=input_type)


_TRACER = _EscLatencyTracer() if _ENABLED else None


def tracer() -> Optional[_EscLatencyTracer]:
    """Return the shared tracer instance (or None when disabled)."""
    return _TRACER


if _ENABLED:
    _write_log_line("tracer.init", log_path=str(_LOG_PATH))
