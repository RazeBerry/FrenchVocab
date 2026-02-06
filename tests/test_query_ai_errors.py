import sys
import os
from types import SimpleNamespace

sys.path.append(os.path.dirname(__file__))
from _stubs import install_basic_stubs
install_basic_stubs()

import FrenchVocab  # noqa: E402
from core.llm_coordinator import LLMCoordinator  # noqa: E402


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
    coordinator._api_error_reason = None
    coordinator._provider_metadata = _MockProviderMetadata()
    coordinator._session_usage = {}
    coordinator._session_requests = 0
    coordinator._on_degraded_mode = None

    # Create a minimal builder with the coordinator
    builder = object.__new__(FrenchVocab.FrenchVocabBuilder)
    builder._llm = coordinator
    builder.ui = ui
    builder.console = SimpleNamespace()
    builder.language_config = FrenchVocab.FrenchVocabBuilder.DEFAULT_LANGUAGE_CONFIG

    result = FrenchVocab.FrenchVocabBuilder.query_ai(builder, "mot")

    assert result == ""
    assert ui.errors, "Expected an error message to be emitted"
    message = ui.errors[0]
    assert 'Claude' in message or 'claude' in message.lower()  # provider label should be visible
    assert 'boom' in message  # surface original exception details
    assert ui.metrics == {'ttft': -1, 'tps': -1, 'tokens_out': -1}
