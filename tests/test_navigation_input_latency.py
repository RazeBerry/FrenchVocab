"""Round-trip cost of the interactive input loop.

The CLI is routinely driven over SSH, where every avoidable ``select`` wait and
every avoidable redraw is paid at network latency. These tests pin the two
behaviors that keep that cost proportional to actual keypresses.
"""

from __future__ import annotations

import os

import pytest

import vocab_builder.cli.navigation as navigation


@pytest.fixture
def escape_pipe():
    read_fd, write_fd = os.pipe()
    try:
        yield read_fd, write_fd
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.fixture
def select_timeouts(monkeypatch):
    """Record the timeout requested by every ``select`` call."""
    recorded: list[float] = []
    real_select = navigation.select.select

    def recording_select(rlist, wlist, xlist, timeout):
        recorded.append(timeout)
        return real_select(rlist, wlist, xlist, timeout)

    monkeypatch.setattr(navigation.select, "select", recording_select)
    return recorded


@pytest.mark.parametrize(
    ("written", "expected_remainder", "expected_key"),
    [
        (b"[A", "[A", "up"),
        (b"[B", "[B", "down"),
        (b"OA", "OA", "up"),
        (b"[1;5A", "[1;5A", "unknown"),
    ],
)
def test_complete_sequence_does_not_wait_for_another_byte(
    escape_pipe, select_timeouts, written, expected_remainder, expected_key
):
    read_fd, write_fd = escape_pipe
    os.write(write_fd, written)

    remainder = navigation._read_escape_remainder(read_fd)

    assert remainder == expected_remainder
    assert navigation._map_escape_remainder(remainder) == expected_key
    # One trailing wait per sequence would be a full timeout that always expires.
    blocking_waits = [t for t in select_timeouts if t == navigation._ESC_SEQUENCE_TIMEOUT]
    assert len(blocking_waits) == len(written) - 1


def test_bare_escape_still_reports_escape(escape_pipe):
    read_fd, _write_fd = escape_pipe

    assert navigation._read_escape_remainder(read_fd) == ""
    assert navigation._map_escape_remainder("") == "escape"


def test_incomplete_sequence_still_waits_for_the_final_byte(escape_pipe, select_timeouts):
    read_fd, write_fd = escape_pipe
    os.write(write_fd, b"[")

    assert navigation._read_escape_remainder(read_fd) == "["
    assert navigation._ESC_SEQUENCE_TIMEOUT in select_timeouts


@pytest.mark.parametrize(
    ("sequence", "complete"),
    [
        (["["], False),
        (["[", "A"], True),
        (["[", "1"], False),
        (["[", "1", ";", "5", "A"], True),
        (["O"], False),
        (["O", "A"], True),
        (["b"], True),
    ],
)
def test_escape_sequence_completion_rules(sequence, complete):
    assert navigation._escape_sequence_is_complete(sequence) is complete


def test_menus_redraw_only_on_change(monkeypatch):
    """Rich's refresh thread would restream the panel ~24x/second while idle."""
    constructed: list[dict] = []

    class _Live:
        def __init__(self, _renderable, **kwargs):
            constructed.append(kwargs)
            self.updates: list[bool] = []

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def update(self, _renderable, *, refresh: bool = False) -> None:
            self.updates.append(refresh)

    monkeypatch.setattr(navigation, "Live", _Live)
    monkeypatch.setattr(navigation, "_flush_stdin", lambda: None)
    monkeypatch.setattr(navigation, "_raw_mode", _noop_context)
    monkeypatch.setattr(navigation.sys, "stdin", _Stdin())
    monkeypatch.setattr(navigation, "_read_key", _scripted_keys(["down", "enter"]))

    console = _RecordingConsole()
    result = navigation.interactive_select(
        console, "Menu", [("add", "Add"), ("exit", "Exit")]
    )

    assert result == "exit"
    assert constructed == [{"console": console, "transient": True, "auto_refresh": False}]


def _scripted_keys(keys):
    remaining = list(keys)

    def _next_key() -> str:
        return remaining.pop(0)

    return _next_key


class _Stdin:
    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 0


class _RecordingConsole:
    def __init__(self) -> None:
        from types import SimpleNamespace

        self.size = SimpleNamespace(width=80)

    def show_cursor(self, _visible: bool) -> None:
        pass

    def print(self, *_args, **_kwargs) -> None:
        pass


def _noop_context(_stream):
    from contextlib import nullcontext

    return nullcontext()
