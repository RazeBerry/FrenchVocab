from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import vocab_builder.cli.navigation as navigation


class _Console:
    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.size = SimpleNamespace(width=80)

    def input(self, _prompt: str) -> str:
        value = self._responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def print(self, *_args, **_kwargs) -> None:
        pass

    def show_cursor(self, _visible: bool) -> None:
        pass


def test_fallback_select_uses_default_key_on_blank_input(monkeypatch):
    console = _Console([""])
    monkeypatch.setattr(navigation.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    result = navigation.interactive_select(
        console,
        "Language",
        [("de", "German"), ("fr", "French")],
        default_key="fr",
    )

    assert result == "fr"


def test_fallback_select_raises_keyboard_interrupt_on_eof(monkeypatch):
    console = _Console([EOFError()])
    monkeypatch.setattr(navigation.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    with pytest.raises(KeyboardInterrupt):
        navigation.interactive_select(
            console,
            "Language",
            [("de", "German"), ("fr", "French")],
        )


def test_fallback_confirm_returns_false_on_eof(monkeypatch):
    console = _Console([EOFError()])
    monkeypatch.setattr(navigation.sys, "stdin", SimpleNamespace(isatty=lambda: False))

    assert navigation.interactive_confirm(console, "Proceed?", default=True) is False


def test_interactive_confirm_treats_ctrl_c_as_cancel(monkeypatch):
    console = _Console()
    monkeypatch.setattr(navigation.sys, "stdin", SimpleNamespace(isatty=lambda: True))

    @contextmanager
    def _raw_mode(_stream):
        yield

    @contextmanager
    def _live(*_args, **_kwargs):
        yield SimpleNamespace(update=lambda *_a, **_k: None)

    monkeypatch.setattr(navigation, "_raw_mode", _raw_mode)
    monkeypatch.setattr(navigation, "Live", _live)
    monkeypatch.setattr(navigation, "_read_key", lambda: "ctrl_c")

    assert navigation.interactive_confirm(console, "Proceed?", default=True) is False
