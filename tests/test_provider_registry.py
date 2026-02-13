import pytest

from core.providers.manager import _get_provider_metadata


def test_unknown_provider_raises_value_error():
    with pytest.raises(ValueError) as exc:
        _get_provider_metadata("openai")
    assert "Unknown provider" in str(exc.value)


def test_default_provider_when_none():
    metadata = _get_provider_metadata(None)
    assert metadata.identifier == "gemini"
