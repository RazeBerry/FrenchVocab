import importlib.util
from pathlib import Path

import pytest

from vocab_builder.core.providers.manager import _get_provider_metadata


def _load_actual_llm_client():
    module_path = Path(__file__).resolve().parent.parent / "vocab_builder" / "llm_client.py"
    spec = importlib.util.spec_from_file_location("llm_client_actual_provider_tests", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_unknown_provider_raises_value_error():
    with pytest.raises(ValueError) as exc:
        _get_provider_metadata("openai")
    assert "Unknown provider" in str(exc.value)


def test_default_provider_when_none():
    metadata = _get_provider_metadata(None)
    assert metadata.identifier == "gemini"


def test_default_provider_prefers_saved_env_credentials(tmp_path, monkeypatch):
    llm_client = _load_actual_llm_client()
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=sk-ant-" + "x" * 40 + "\n", encoding="utf-8")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("FRENCHVOCAB_TEST_PROVIDER_AUTODETECT", "1")
    monkeypatch.setattr(llm_client, "_candidate_env_paths", lambda: (env_path,))

    assert llm_client.ProviderFactory.default_provider() == "claude"


def test_default_provider_prefers_saved_keyring_credentials(tmp_path, monkeypatch):
    llm_client = _load_actual_llm_client()
    env_path = tmp_path / ".env"

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("FRENCHVOCAB_TEST_PROVIDER_AUTODETECT", "1")
    monkeypatch.setattr(llm_client, "_candidate_env_paths", lambda: (env_path,))

    def _fake_get_password(_service: str, name: str):
        if name == "anthropic_api_key":
            return "sk-ant-" + "y" * 40
        return None

    monkeypatch.setattr(llm_client, "_keyring_get_password_best_effort", _fake_get_password)

    assert llm_client.ProviderFactory.default_provider() == "claude"
