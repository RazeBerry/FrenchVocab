"""Startup warm-up scheduling for the vocabulary controller.

Parsing the LaTeX index is the one expensive step of startup that nothing else
depends on, so it runs on a background thread. Scheduling lives here rather
than on the controller to keep that policy in one place.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable


def sync_load_requested() -> bool:
    """Report whether entries must be parsed synchronously during startup."""
    from vocab_builder.compat import get_env

    return bool(
        os.environ.get("PYTEST_CURRENT_TEST") or get_env("VOCABBUILDER_FORCE_SYNC_LOAD")
    )


def start_entry_warmup(app: Any) -> None:
    """Begin parsing the LaTeX index without blocking the caller.

    The first menu refresh needs an authoritative entry count and therefore
    blocks on this parse, so scheduling it before provider initialization lets
    the two overlap instead of leaving the parse in front of the welcome
    screen.
    """
    if sync_load_requested() or getattr(app, "_entries_loaded", False):
        return

    thread = threading.Thread(
        target=_run_safely,
        args=(app, app._ensure_entries_loaded, "entries"),
        name="warmup-entries",
        daemon=True,
    )
    thread.start()
    app._warmup_threads.append(thread)


def _run_safely(app: Any, task: Callable[[], None], label: str) -> None:
    """Run a warm-up task defensively so background failures never block startup."""
    try:
        task()
    except Exception as exc:  # pragma: no cover - best-effort telemetry
        if app.verbose:
            app.ui.debug(f"Warm-up task failed [{label}]: {exc}")


__all__ = ["start_entry_warmup", "sync_load_requested"]
