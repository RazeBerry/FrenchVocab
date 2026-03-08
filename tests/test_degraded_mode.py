import FrenchVocab
import threading
import os
from types import SimpleNamespace

from core.llm_coordinator import LLMCoordinator, InitState


class _DummyClient:
    def stream(self, _prompt: str):
        yield ""


class _RejectingClient:
    def verify_credentials(self, timeout=5.0):  # noqa: ARG002
        raise RuntimeError("invalid api key")


def _make_minimal_coordinator(provider: str = "gemini") -> LLMCoordinator:
    coordinator = object.__new__(LLMCoordinator)
    coordinator._state_lock = threading.Lock()
    coordinator._init_event = threading.Event()
    coordinator._ui = type(
        "_UI",
        (),
        {
            "warning": staticmethod(lambda *_args, **_kwargs: None),
            "info": staticmethod(lambda *_args, **_kwargs: None),
            "success": staticmethod(lambda *_args, **_kwargs: None),
            "error": staticmethod(lambda *_args, **_kwargs: None),
        },
    )()
    coordinator._provider_metadata = SimpleNamespace(identifier=provider)
    coordinator._client = None
    coordinator._api_error_reason = None
    coordinator._init_state = InitState.NOT_STARTED
    coordinator._init_generation = 0
    coordinator._session_usage = {}
    coordinator._session_requests = 0
    coordinator._llm_thread = None
    coordinator._on_degraded_mode = None
    coordinator._on_client_ready = None
    coordinator._verbose = False
    return coordinator


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

    def _prepare(self, *, generation=None):  # noqa: ARG001
        call_state["count"] += 1
        if call_state["count"] == 1:
            self._api_error_reason = "initial failure"
            return False
        self._api_error_reason = None
        return True

    def _initialize_client(self, *, announce=True, on_success=None, generation=None):  # noqa: ARG001
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


def test_background_init_wait_timeout_does_not_block_forever(monkeypatch):
    coordinator = object.__new__(LLMCoordinator)
    coordinator._state_lock = threading.Lock()
    coordinator._init_state = InitState.IN_PROGRESS
    coordinator._init_event = type(
        "_Event",
        (),
        {
            "wait": staticmethod(lambda timeout=None: False),
            "set": staticmethod(lambda: None),
        },
    )()
    coordinator._ui = type(
        "_UI",
        (),
        {
            "warning": staticmethod(lambda message: None),
            "info": staticmethod(lambda message: None),
        },
    )()

    assert coordinator._wait_for_background_init_if_needed() is False
    assert coordinator.init_state == InitState.FAILED
    assert coordinator.api_error_reason == "Background provider initialization timed out. Retry setup to continue."


def test_stale_generation_failure_does_not_clear_current_client(monkeypatch):
    import llm_client

    coordinator = _make_minimal_coordinator("claude")
    existing_client = _DummyClient()
    coordinator._client = existing_client
    coordinator._init_state = InitState.READY
    coordinator._init_generation = 2

    def _raise_invalid_key(_provider_name: str):
        raise RuntimeError("invalid api key")

    monkeypatch.setattr(llm_client.ProviderFactory, "create", _raise_invalid_key)

    assert coordinator._initialize_client(generation=1) is False
    assert coordinator.client is existing_client
    assert coordinator.init_state == InitState.READY
    assert coordinator.api_error_reason is None


def test_initialize_client_degrades_cleanly_on_auth_failure(monkeypatch):
    import llm_client

    coordinator = _make_minimal_coordinator("claude")
    coordinator._init_state = InitState.IN_PROGRESS
    coordinator._init_generation = 1

    monkeypatch.setattr(llm_client.ProviderFactory, "create", lambda _provider_name: _RejectingClient())
    monkeypatch.setattr(
        LLMCoordinator,
        "_classify_provider_error",
        staticmethod(lambda _provider, _exc: ("auth", "Anthropic Claude credentials were rejected or revoked.")),
    )

    assert coordinator._initialize_client(generation=1) is False
    assert coordinator.client is None
    assert coordinator.init_state == InitState.FAILED
    assert "rejected or revoked" in (coordinator.api_error_reason or "")


def test_stale_provider_resolution_does_not_overwrite_current_state(monkeypatch):
    coordinator = _make_minimal_coordinator("claude")
    coordinator._api_error_reason = "keep current state"
    coordinator._init_generation = 2
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    resolution = SimpleNamespace(
        metadata=SimpleNamespace(identifier="gemini", env_var="GEMINI_API_KEY"),
        api_key="AIza" + "x" * 36,
    )

    assert coordinator._apply_provider_resolution(resolution, generation=1) is False
    assert coordinator.provider == "claude"
    assert coordinator.api_error_reason == "keep current state"
    assert os.environ.get("GEMINI_API_KEY") is None
