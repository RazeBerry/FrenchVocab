from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

from vocab_builder.core import VocabBuilder
from vocab_builder.core.llm_coordinator import InitState, LLMCoordinator


class _FailingClient:
    def stream(self, _prompt: str):
        def _gen():
            raise RuntimeError("boom")
            yield ""
        return _gen()

    def model_label(self):
        return "Stub Claude"


class _CaptureUI:
    def __init__(self):
        self.errors = []
        self.metrics = None

    def error(self, text: str, with_panel: bool = False):
        self.errors.append(text)

    def display_metrics(self, metrics):
        self.metrics = metrics

    # Provide no-op hooks used elsewhere so the builder doesn't break if invoked
    def info(self, *_args, **_kwargs):
        pass
    def warning(self, *_args, **_kwargs):
        pass
    def success(self, *_args, **_kwargs):
        pass
    def panel(self, *_args, **_kwargs):
        pass
    def display_menu(self, *_args, **_kwargs):
        pass
    def interactive_menu(self, _title, options, *_args, **_kwargs):
        return options[0][0] if options else ""
    def quick_table(self, *_args, **_kwargs):
        pass
    def dict_to_table(self, *_args, **_kwargs):
        pass


class _MockProviderMetadata:
    identifier = "claude"
    display_name = "Claude"
    env_var = "ANTHROPIC_API_KEY"
    keyring_name = "anthropic"


class _MockProviderManager:
    def prepare_provider(self, *args, **kwargs):
        raise RuntimeError("No setup needed for test")

    def resolve_provider_silently(self, *args, **kwargs):
        return None


def test_query_ai_surfaces_provider_error_label():
    ui = _CaptureUI()
    client = _FailingClient()

    # Create a minimal LLMCoordinator with the failing client injected
    import threading
    coordinator = object.__new__(LLMCoordinator)
    coordinator._ui = ui
    coordinator._client = client
    coordinator._state_lock = threading.Lock()
    coordinator._query_lock = threading.Lock()
    coordinator._usage_lock = threading.Lock()
    coordinator._api_error_reason = None
    coordinator._provider_metadata = _MockProviderMetadata()
    coordinator._session_usage = {}
    coordinator._session_requests = 0
    coordinator._on_degraded_mode = None

    # Create a minimal builder with the coordinator
    builder = object.__new__(VocabBuilder)
    builder._llm = coordinator
    builder.ui = ui
    builder.console = SimpleNamespace()
    builder.language_config = VocabBuilder.DEFAULT_LANGUAGE_CONFIG

    result = VocabBuilder.query_ai(builder, "mot")

    assert result == ""
    assert ui.errors, "Expected an error message to be emitted"
    message = ui.errors[0]
    assert 'Claude' in message or 'claude' in message.lower()  # provider label should be visible
    assert 'boom' in message  # surface original exception details
    assert ui.metrics == {'ttft': -1, 'tps': -1, 'tokens_out': -1}


def test_handle_ai_exception_degrades_cleanly_on_quota_failure(monkeypatch):
    ui = _CaptureUI()
    ui.interactive_menu = lambda *_args, **_kwargs: "skip"

    import threading
    coordinator = object.__new__(LLMCoordinator)
    coordinator._ui = ui
    coordinator._client = _FailingClient()
    coordinator._state_lock = threading.Lock()
    coordinator._query_lock = threading.Lock()
    coordinator._usage_lock = threading.Lock()
    coordinator._init_event = threading.Event()
    coordinator._init_generation = 1
    coordinator._init_state = InitState.READY
    coordinator._api_error_reason = None
    coordinator._provider_metadata = _MockProviderMetadata()
    coordinator._session_usage = {}
    coordinator._session_requests = 0
    coordinator._on_degraded_mode = None
    coordinator._on_client_ready = None

    monkeypatch.setattr(
        LLMCoordinator,
        "_classify_provider_error",
        staticmethod(lambda _provider, _exc: ("quota", "Anthropic Claude quota is exhausted or unavailable.")),
    )
    handled = coordinator.handle_ai_exception(RuntimeError("quota exceeded"), "Claude")

    assert handled is True
    assert coordinator.api_available is False
    assert "quota" in (coordinator.api_error_reason or "").lower()


def test_transient_provider_error_preserves_ready_state_and_precise_reason(monkeypatch):
    class TransientClient:
        def model_label(self):
            return "Anthropic Claude (test)"

        def stream(self, _prompt):
            raise RuntimeError(
                "503 UNAVAILABLE. {'error': {'code': 503, 'message': "
                "'This model is currently experiencing high demand.'}}"
            )
            yield ""  # pragma: no cover - keeps this a generator

    ui = _CaptureUI()
    coordinator = LLMCoordinator(
        ui,
        provider_manager=SimpleNamespace(),
        provider_metadata=_MockProviderMetadata(),
        client=TransientClient(),
        interactive=False,
    )
    reason = (
        "Anthropic Claude rejected the request with 503 UNAVAILABLE "
        "(reported high demand)."
    )
    monkeypatch.setattr(
        LLMCoordinator,
        "_classify_provider_error",
        staticmethod(lambda _provider, _exc: ("transient", reason)),
    )

    response, _metrics = coordinator.query(
        "prompt",
        on_exception=lambda exc, label: coordinator.handle_ai_exception(
            exc,
            label,
        ),
    )

    assert response == ""
    assert coordinator.api_available is True
    assert coordinator.api_error_reason is None
    assert coordinator.last_query_error_reason == reason


def test_queries_on_one_coordinator_are_serialized():
    first_started = threading.Event()
    release_first = threading.Event()
    active_lock = threading.Lock()
    active = 0
    maximum_active = 0

    class GatedClient:
        def model_label(self):
            return "Serialized provider"

        def stream(self, prompt):
            nonlocal active, maximum_active
            with active_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                if prompt == "first":
                    first_started.set()
                    assert release_first.wait(timeout=2)
                yield prompt
                return {}
            finally:
                with active_lock:
                    active -= 1

    coordinator = LLMCoordinator(
        _CaptureUI(),
        provider_manager=SimpleNamespace(),
        provider_metadata=_MockProviderMetadata(),
        client=GatedClient(),
        interactive=False,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(coordinator.query, "first")
        assert first_started.wait(timeout=1)
        second = executor.submit(coordinator.query, "second")
        assert not second.done()
        release_first.set()

    assert first.result()[0] == "first"
    assert second.result()[0] == "second"
    assert maximum_active == 1


def test_inflight_query_keeps_its_client_snapshot_when_provider_degrades():
    started = threading.Event()
    release = threading.Event()

    class GatedClient:
        def model_label(self):
            return "Snapshot provider"

        def stream(self, _prompt):
            started.set()
            assert release.wait(timeout=2)
            yield "completed"
            return {}

    coordinator = LLMCoordinator(
        _CaptureUI(),
        provider_manager=SimpleNamespace(),
        provider_metadata=_MockProviderMetadata(),
        client=GatedClient(),
        interactive=False,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(coordinator.query, "prompt")
        assert started.wait(timeout=1)
        coordinator._enter_degraded_mode("another request failed")
        release.set()

    assert result.result()[0] == "completed"
    assert coordinator.client is None
