import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent))
from _stubs import install_basic_stubs  # type: ignore


install_basic_stubs()

import FrenchVocab  # noqa: E402,F401
from core.vocab import _get_provider_metadata  # noqa: E402


def test_unknown_provider_raises_value_error():
    with pytest.raises(ValueError) as exc:
        _get_provider_metadata("openai")
    assert "Unknown provider" in str(exc.value)


def test_default_provider_when_none():
    metadata = _get_provider_metadata(None)
    assert metadata.identifier == "gemini"
