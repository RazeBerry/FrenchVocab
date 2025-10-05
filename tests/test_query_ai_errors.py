import sys
import os
from types import SimpleNamespace

sys.path.append(os.path.dirname(__file__))
from _stubs import install_basic_stubs
install_basic_stubs()

import FrenchVocab


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
    def quick_table(self, *_args, **_kwargs):
        pass
    def dict_to_table(self, *_args, **_kwargs):
        pass


def test_query_ai_surfaces_provider_error_label():
    builder = object.__new__(FrenchVocab.FrenchVocabBuilder)
    builder.provider = 'claude'
    builder.client = _FailingClient()
    builder.ui = _CaptureUI()
    builder.console = SimpleNamespace()

    result = FrenchVocab.FrenchVocabBuilder.query_ai(builder, "mot")

    assert result == ""
    assert builder.ui.errors, "Expected an error message to be emitted"
    message = builder.ui.errors[0]
    assert 'Claude' in message  # provider label should be visible
    assert 'boom' in message  # surface original exception details
    assert builder.ui.metrics == {'ttft': -1, 'tps': -1, 'tokens_out': -1}
