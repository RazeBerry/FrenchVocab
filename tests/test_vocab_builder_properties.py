from pathlib import Path
from types import SimpleNamespace

import pytest

from vocab_builder.core.vocab import FrenchVocabBuilder


def test_word_entries_property_uses_repo_and_triggers_lazy_load() -> None:
    builder = object.__new__(FrenchVocabBuilder)
    called = {"count": 0}

    def _ensure_loaded() -> None:
        called["count"] += 1

    repo = SimpleNamespace(
        word_entries={"bonjour": {"word": "Bonjour"}},
        normalized_entries={"bonjour": "bonjour"},
        ensure_entries_loaded=_ensure_loaded,
        entry_count=0,
    )
    builder._vocab_repo = repo

    entries = builder.word_entries
    normalized = builder.normalized_entries

    assert entries["bonjour"]["word"] == "Bonjour"
    assert normalized["bonjour"] == "bonjour"
    assert called["count"] == 2


def test_word_entries_and_normalized_entries_fallback_for_test_doubles() -> None:
    builder = object.__new__(FrenchVocabBuilder)
    builder.word_entries = {"salut": {"word": "Salut"}}
    builder.normalized_entries = {"salut": "salut"}

    assert builder.word_entries["salut"]["word"] == "Salut"
    assert builder.normalized_entries["salut"] == "salut"


def test_word_entries_raise_clear_error_when_uninitialized() -> None:
    builder = object.__new__(FrenchVocabBuilder)

    with pytest.raises(RuntimeError):
        _ = builder.word_entries

    with pytest.raises(RuntimeError):
        _ = builder.normalized_entries


def test_load_input_limits_ignores_malformed_config_before_llm_init(tmp_path) -> None:
    class _StubUI:
        def __init__(self) -> None:
            self.debug_messages = []

        def debug(self, message: str) -> None:
            self.debug_messages.append(message)

    builder = object.__new__(FrenchVocabBuilder)
    builder.ui = _StubUI()
    builder.config_file = str(tmp_path / "malformed-config.json")
    builder._config_data = {}
    builder._verbose_fallback = True
    Path(builder.config_file).write_text("{not-json", encoding="utf-8")

    builder._load_input_limits_from_config_file()

    assert builder._config_data == {}
    assert builder.ui.debug_messages


def test_keyring_get_password_best_effort_swallows_keyring_errors(monkeypatch) -> None:
    import keyring
    from keyring.errors import KeyringError

    def _raise_keyring_error(*_args, **_kwargs):
        raise KeyringError("backend locked")

    monkeypatch.setattr(keyring, "get_password", _raise_keyring_error)

    value = FrenchVocabBuilder._keyring_get_password_best_effort(
        "french_vocab_builder",
        "gemini_api_key",
    )

    assert value is None
