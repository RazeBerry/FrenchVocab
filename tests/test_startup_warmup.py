"""Scheduling rules for the background LaTeX parse performed at startup."""

from __future__ import annotations

import threading

from vocab_builder.core import startup_warmup


class _RecordingUI:
    def __init__(self) -> None:
        self.debug_messages: list[str] = []

    def debug(self, message: str) -> None:
        self.debug_messages.append(message)


class _App:
    """Minimal stand-in for the parts of VocabBuilder the warm-up touches."""

    def __init__(self, *, error: Exception | None = None, entries_loaded: bool = False) -> None:
        self.ui = _RecordingUI()
        self.verbose = True
        self._entries_loaded = entries_loaded
        self._warmup_threads: list[threading.Thread] = []
        self._error = error
        self.parse_calls = 0
        self.parse_thread: threading.Thread | None = None

    def _ensure_entries_loaded(self) -> None:
        self.parse_calls += 1
        self.parse_thread = threading.current_thread()
        if self._error is not None:
            raise self._error


def _force_async_startup(monkeypatch) -> None:
    """Undo the test-runner markers that force a synchronous parse.

    This must run inside the test body: pytest re-exports PYTEST_CURRENT_TEST
    at the start of every phase, so clearing it from a fixture would be undone
    before the assertions run.
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("VOCABBUILDER_FORCE_SYNC_LOAD", raising=False)


def test_sync_load_requested_under_pytest():
    assert startup_warmup.sync_load_requested() is True


def test_sync_load_requested_honors_the_env_override(monkeypatch):
    _force_async_startup(monkeypatch)
    assert startup_warmup.sync_load_requested() is False
    monkeypatch.setenv("VOCABBUILDER_FORCE_SYNC_LOAD", "1")
    assert startup_warmup.sync_load_requested() is True


def test_no_thread_is_started_when_the_parse_must_be_synchronous():
    app = _App()

    startup_warmup.start_entry_warmup(app)

    assert app._warmup_threads == []
    assert app.parse_calls == 0


def test_entries_are_parsed_off_the_calling_thread(monkeypatch):
    _force_async_startup(monkeypatch)
    app = _App()

    startup_warmup.start_entry_warmup(app)

    assert len(app._warmup_threads) == 1
    app._warmup_threads[0].join(timeout=5)
    assert app.parse_calls == 1
    assert app.parse_thread is not threading.current_thread()


def test_already_loaded_entries_are_not_reparsed(monkeypatch):
    _force_async_startup(monkeypatch)
    app = _App(entries_loaded=True)

    startup_warmup.start_entry_warmup(app)

    assert app._warmup_threads == []
    assert app.parse_calls == 0


def test_a_failing_warmup_never_reaches_the_caller(monkeypatch):
    _force_async_startup(monkeypatch)
    app = _App(error=RuntimeError("unreadable collection"))

    startup_warmup.start_entry_warmup(app)
    app._warmup_threads[0].join(timeout=5)

    assert app.ui.debug_messages == [
        "Warm-up task failed [entries]: unreadable collection"
    ]
