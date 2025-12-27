import os
import sys

sys.path.append(os.path.dirname(__file__))
from _stubs import install_basic_stubs  # type: ignore

install_basic_stubs()

import FrenchVocab  # noqa: E402
from core.llm_coordinator import LLMCoordinator, InitState  # noqa: E402


class _DummyClient:
    def stream(self, _prompt: str):
        yield ""


def test_builder_enters_degraded_mode_when_setup_fails(monkeypatch, tmp_path):
    def _failing_prepare(self):
        self._api_error_reason = "forced failure"
        return False

    monkeypatch.setattr(LLMCoordinator, "_prepare_provider", _failing_prepare)

    builder = FrenchVocab.FrenchVocabBuilder(
        latex_file=str(tmp_path / "vocab.tex"),
        provider="gemini",
    )

    assert builder.client is None
    assert builder.api_available is False
    assert builder.api_error_reason == "forced failure"
    assert builder.eng_to_fr_translator is None
    assert builder.fr_to_eng_translator is None


def test_reconfigure_provider_restores_client(monkeypatch, tmp_path):
    call_state = {"count": 0}

    def _prepare(self):
        call_state["count"] += 1
        if call_state["count"] == 1:
            self._api_error_reason = "initial failure"
            return False
        self._api_error_reason = None
        return True

    def _initialize_client(self, *, announce=True, on_success=None):
        self._client = _DummyClient()
        with self._state_lock:
            self._init_state = InitState.READY
            self._api_error_reason = None
            self._init_event.set()
        if on_success:
            on_success()
        return True

    monkeypatch.setattr(LLMCoordinator, "_prepare_provider", _prepare)
    monkeypatch.setattr(LLMCoordinator, "_initialize_client", _initialize_client)

    builder = FrenchVocab.FrenchVocabBuilder(
        latex_file=str(tmp_path / "reconfigure.tex"),
        provider="gemini",
    )

    assert builder.client is None
    assert builder.api_available is False
    assert builder.api_error_reason == "initial failure"

    restored = builder.reconfigure_provider()

    assert restored is True
    assert isinstance(builder.client, _DummyClient)
    assert builder.api_available is True
    assert builder.api_error_reason is None
    assert builder.eng_to_fr_translator is not None
    assert builder.fr_to_eng_translator is not None


def test_ensure_llm_ready_skip_returns_false(monkeypatch, tmp_path):
    def _prepare(self):
        self._api_error_reason = "no credentials"
        return False

    monkeypatch.setattr(LLMCoordinator, "_prepare_provider", _prepare)

    builder = FrenchVocab.FrenchVocabBuilder(
        latex_file=str(tmp_path / "ensure.tex"),
        provider="gemini",
    )

    assert builder.client is None

    prompts = {"count": 0}

    def _interactive_menu(_title, options, *_args, **_kwargs):
        prompts["count"] += 1
        return "skip"

    # Silence UI noise during the prompt - patch on coordinator's ui
    monkeypatch.setattr(builder._llm._ui, "interactive_menu", _interactive_menu)
    monkeypatch.setattr(builder._llm._ui, "warning", lambda *_a, **_k: None)
    monkeypatch.setattr(builder._llm._ui, "info", lambda *_a, **_k: None)

    result = builder.ensure_llm_ready()

    assert result is False
    assert prompts["count"] == 1
    assert builder.client is None
