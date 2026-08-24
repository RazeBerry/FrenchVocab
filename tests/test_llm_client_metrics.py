import importlib
import os
import sys
import types
from types import SimpleNamespace

import pytest


class _Models:
    def __init__(self, response_factory=None):
        self.last_generate_kwargs = None
        self.last_count_kwargs = None
        self.generate_calls = 0
        self.count_calls = 0
        self._response_factory = response_factory or (
            lambda: SimpleNamespace(text="helloworld", usage_metadata=None)
        )

    def generate_content(self, **kwargs):
        self.generate_calls += 1
        self.last_generate_kwargs = kwargs
        return self._response_factory()

    def count_tokens(self, **kwargs):
        self.count_calls += 1
        self.last_count_kwargs = kwargs
        return SimpleNamespace(total_tokens=5)


class _Client:
    def __init__(self, api_key=None, response_factory=None, http_options=None):
        self.api_key = api_key
        self.http_options = http_options
        self.models = _Models(response_factory)


class _Part:
    @staticmethod
    def from_text(*, text: str):
        return {"text": text}


class _Content:
    def __init__(self, role: str, parts):
        self.role = role
        self.parts = parts


class _GenerateContentConfig:
    def __init__(self, **_kwargs):
        self.kwargs = _kwargs


class _ThinkingConfig:
    def __init__(self, **_kwargs):
        self.kwargs = _kwargs


class _ThinkingLevel:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class _AutomaticFunctionCallingConfig:
    def __init__(self, **_kwargs):
        self.kwargs = _kwargs


class _HttpOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _HttpRetryOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _install_google_stub(response_factory=None):
    saved = {
        name: sys.modules.get(name)
        for name in ("google", "google.genai", "google.genai.types")
    }

    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")
    types_mod.Content = _Content
    types_mod.Part = _Part
    types_mod.GenerateContentConfig = _GenerateContentConfig
    types_mod.ThinkingConfig = _ThinkingConfig
    types_mod.ThinkingLevel = _ThinkingLevel
    types_mod.AutomaticFunctionCallingConfig = _AutomaticFunctionCallingConfig
    types_mod.HttpOptions = _HttpOptions
    types_mod.HttpRetryOptions = _HttpRetryOptions

    genai_mod.Client = lambda api_key=None, http_options=None: _Client(
        api_key=api_key,
        response_factory=response_factory,
        http_options=http_options,
    )
    genai_mod.types = types_mod

    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod

    return saved


def _restore_google_stub(saved):
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class _ClaudeMessageStream:
    def __init__(self):
        self.text_stream = iter(["hello", "world"])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_final_message(self):
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=7, output_tokens=11)
        )


class _ClaudeMessages:
    def __init__(self):
        self.last_stream_kwargs = None

    def stream(self, **kwargs):
        self.last_stream_kwargs = kwargs
        return _ClaudeMessageStream()


class _ClaudeModels:
    def list(self):
        return []


class _ClaudeClient:
    def __init__(self, api_key=None, timeout=None):
        self.api_key = api_key
        self.timeout = timeout
        self.messages = _ClaudeMessages()
        self.models = _ClaudeModels()


def _install_anthropic_stub():
    saved = sys.modules.get("anthropic")
    clients = []

    anthropic_mod = types.ModuleType("anthropic")

    def _create_client(api_key=None, timeout=None):
        client = _ClaudeClient(api_key=api_key, timeout=timeout)
        clients.append(client)
        return client

    anthropic_mod.Anthropic = _create_client
    sys.modules["anthropic"] = anthropic_mod
    return saved, clients


def _restore_anthropic_stub(saved):
    if saved is None:
        sys.modules.pop("anthropic", None)
    else:
        sys.modules["anthropic"] = saved


def _load_real_llm_client():
    sys.modules.pop("vocab_builder.llm_client", None)
    sys.modules.pop("llm_client", None)
    llm_client = importlib.import_module("vocab_builder.llm_client")
    return importlib.reload(llm_client)


def _consume_stream(generator):
    chunks = []
    while True:
        try:
            chunks.append(next(generator))
        except StopIteration as stop:
            return "".join(chunks), stop.value


def _clear_model_env(monkeypatch):
    for name in (
        "VOCABBUILDER_CLAUDE_MODEL",
        "VOCABBUILDER_GEMINI_MODEL",
        "FRENCHVOCAB_CLAUDE_MODEL",
        "FRENCHVOCAB_GEMINI_MODEL",
        "FRENCH_VOCAB_CLAUDE_MODEL",
        "FRENCH_VOCAB_GEMINI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_transient_classifier_only_reports_high_demand_when_provider_does():
    llm_client = _load_real_llm_client()

    generic = llm_client.classify_provider_error(
        "gemini",
        RuntimeError("503 UNAVAILABLE: service unavailable"),
    )
    reported_demand = llm_client.classify_provider_error(
        "gemini",
        RuntimeError("503 UNAVAILABLE: model is experiencing high demand"),
    )

    assert generic == (
        "transient",
        "Google Gemini rejected the request with 503 UNAVAILABLE.",
    )
    assert reported_demand == (
        "transient",
        "Google Gemini rejected the request with 503 UNAVAILABLE "
        "(reported high demand).",
    )


def test_gemini_client_does_not_send_a_second_request_for_missing_usage(tmp_path):
    os.environ["GEMINI_API_KEY"] = "AIza" + "x" * 36
    saved = _install_google_stub()
    try:
        sys.modules.pop("vocab_builder.llm_client", None)
        sys.modules.pop("llm_client", None)
        llm_client = importlib.import_module("vocab_builder.llm_client")
        llm_client = importlib.reload(llm_client)

        client = llm_client.GeminiClient()
        stream = client.stream("prompt")
        chunks = []
        while True:
            try:
                chunks.append(next(stream))
            except StopIteration as stop:
                metrics = stop.value
                break
        assert "".join(chunks) == "helloworld"

        models = client._client.models
        payload = models.last_generate_kwargs["contents"]
        assert isinstance(payload, list)
        assert len(payload) == 1
        content = payload[0]
        assert getattr(content, "role", None) == "user"
        assert content.parts[0]["text"] == "prompt"
        assert models.generate_calls == 1
        assert models.count_calls == 0
        assert metrics["tokens_out"] == 0
        assert "usage" not in metrics
    finally:
        _restore_google_stub(saved)


def test_gemini_disables_google_sdk_retries(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    saved = _install_google_stub()
    try:
        llm_client = _load_real_llm_client()
        client = llm_client.GeminiClient()
        retry_options = client._client.http_options.kwargs["retry_options"]

        assert retry_options.kwargs == {
            "attempts": 1,
        }
        assert not hasattr(client, "_fallback_client")
    finally:
        _restore_google_stub(saved)


def test_gemini_surfaces_503_after_exactly_one_generation_call(monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    _clear_model_env(monkeypatch)
    saved = _install_google_stub()
    try:
        llm_client = _load_real_llm_client()
        client = llm_client.GeminiClient()

        class PrimaryModels(_Models):
            def generate_content(self, **kwargs):
                self.generate_calls += 1
                self.last_generate_kwargs = kwargs
                raise RuntimeError("503 UNAVAILABLE: model is experiencing high demand")

        primary_models = PrimaryModels()
        client._client.models = primary_models

        with caplog.at_level("WARNING"), pytest.raises(
            RuntimeError,
            match="503 UNAVAILABLE",
        ):
            _consume_stream(client.stream("prompt"))

        assert primary_models.generate_calls == 1
        assert primary_models.last_generate_kwargs["model"] == "gemini-3.7-flash"
        assert "category=transient" in caplog.text
        assert "prompt" not in caplog.text
    finally:
        _restore_google_stub(saved)


def test_gemini_surfaces_non_503_failure_after_one_call(monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    _clear_model_env(monkeypatch)
    saved = _install_google_stub()
    try:
        llm_client = _load_real_llm_client()
        client = llm_client.GeminiClient()

        class FailingModels(_Models):
            def generate_content(self, **kwargs):
                self.generate_calls += 1
                self.last_generate_kwargs = kwargs
                raise RuntimeError("400 INVALID_ARGUMENT")

        failing_models = FailingModels()
        client._client.models = failing_models

        with caplog.at_level("WARNING"), pytest.raises(
            RuntimeError,
            match="INVALID_ARGUMENT",
        ):
            _consume_stream(client.stream("prompt"))

        assert failing_models.generate_calls == 1
        assert "category=unclassified" in caplog.text
        assert "prompt" not in caplog.text
    finally:
        _restore_google_stub(saved)


def test_model_labels_use_default_models_when_env_unset(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    _clear_model_env(monkeypatch)
    google_saved = _install_google_stub()
    anthropic_saved, _clients = _install_anthropic_stub()
    try:
        llm_client = _load_real_llm_client()

        gemini = llm_client.GeminiClient()
        claude = llm_client.ClaudeClient(api_key="sk-ant-" + "x" * 40)

        assert gemini.model_label() == "Google Gemini (gemini-3.7-flash)"
        assert claude.model_label() == "Anthropic Claude (claude-sonnet-4-6)"
    finally:
        _restore_google_stub(google_saved)
        _restore_anthropic_stub(anthropic_saved)


def test_provider_clients_receive_configured_request_deadline(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    monkeypatch.setenv("VOCABBUILDER_PROVIDER_TIMEOUT", "7.5")
    google_saved = _install_google_stub()
    anthropic_saved, clients = _install_anthropic_stub()
    try:
        llm_client = _load_real_llm_client()

        gemini = llm_client.GeminiClient()
        llm_client.ClaudeClient(api_key="sk-ant-" + "x" * 40)

        assert gemini._client.http_options.kwargs["timeout"] == 7500
        assert clients[0].timeout == 7.5
    finally:
        _restore_google_stub(google_saved)
        _restore_anthropic_stub(anthropic_saved)


def test_model_labels_use_env_overrides(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    monkeypatch.setenv("VOCABBUILDER_GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("VOCABBUILDER_CLAUDE_MODEL", "claude-test-model")
    google_saved = _install_google_stub()
    anthropic_saved, _clients = _install_anthropic_stub()
    try:
        llm_client = _load_real_llm_client()

        gemini = llm_client.GeminiClient()
        claude = llm_client.ClaudeClient(api_key="sk-ant-" + "x" * 40)

        assert gemini.model_label() == "Google Gemini (gemini-test-model)"
        assert claude.model_label() == "Anthropic Claude (claude-test-model)"
    finally:
        _restore_google_stub(google_saved)
        _restore_anthropic_stub(anthropic_saved)


def test_model_override_whitespace_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    monkeypatch.setenv("VOCABBUILDER_GEMINI_MODEL", "   ")
    monkeypatch.setenv("VOCABBUILDER_CLAUDE_MODEL", "\t")
    google_saved = _install_google_stub()
    anthropic_saved, _clients = _install_anthropic_stub()
    try:
        llm_client = _load_real_llm_client()

        gemini = llm_client.GeminiClient()
        claude = llm_client.ClaudeClient(api_key="sk-ant-" + "x" * 40)

        assert gemini.model_label() == "Google Gemini (gemini-3.7-flash)"
        assert claude.model_label() == "Anthropic Claude (claude-sonnet-4-6)"
    finally:
        _restore_google_stub(google_saved)
        _restore_anthropic_stub(anthropic_saved)


def test_resolved_models_are_used_for_provider_requests(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)
    monkeypatch.setenv("VOCABBUILDER_GEMINI_MODEL", "gemini-request-model")
    monkeypatch.setenv("VOCABBUILDER_CLAUDE_MODEL", "claude-request-model")
    google_saved = _install_google_stub()
    anthropic_saved, clients = _install_anthropic_stub()
    try:
        llm_client = _load_real_llm_client()

        gemini = llm_client.GeminiClient()
        gemini_text, gemini_metrics = _consume_stream(gemini.stream("prompt"))

        claude = llm_client.ClaudeClient(api_key="sk-ant-" + "x" * 40)
        claude_text, claude_metrics = _consume_stream(claude.stream("prompt"))

        assert gemini_text == "helloworld"
        assert gemini_metrics["tokens_out"] == 0
        assert gemini._client.models.last_generate_kwargs["model"] == "gemini-request-model"
        assert gemini._client.models.last_count_kwargs is None
        gemini_config = gemini._client.models.last_generate_kwargs["config"].kwargs
        assert gemini_config["response_mime_type"] == "text/plain"
        assert gemini_config["max_output_tokens"] == 8192
        assert gemini_config["thinking_config"].kwargs["thinking_level"] == "LOW"
        assert gemini_config["automatic_function_calling"].kwargs == {"disable": True}
        for unsupported_parameter in (
            "temperature",
            "top_p",
            "top_k",
            "thinking_budget",
            "candidate_count",
        ):
            assert unsupported_parameter not in gemini_config

        assert claude_text == "helloworld"
        assert claude_metrics["usage"]["prompt_tokens"] == 7
        assert claude_metrics["usage"]["output_tokens"] == 11
        stream_kwargs = clients[0].messages.last_stream_kwargs
        assert stream_kwargs["model"] == "claude-request-model"
        assert stream_kwargs["max_tokens"] == 8192
        assert stream_kwargs["temperature"] == 0.1
        assert "extra_headers" not in stream_kwargs
        assert "top_p" not in stream_kwargs
        assert "thinking" not in stream_kwargs
    finally:
        _restore_google_stub(google_saved)
        _restore_anthropic_stub(anthropic_saved)


def test_gemini_client_reports_usage_metadata(tmp_path):
    os.environ["GEMINI_API_KEY"] = "AIza" + "x" * 36

    def response_factory():
        return SimpleNamespace(
            text="helloworld",
            usage_metadata=SimpleNamespace(
                prompt_token_count=11,
                candidates_token_count=23,
                total_token_count=34,
                thoughts_token_count=5,
                tool_use_prompt_token_count=None,
                cached_content_token_count=None,
            )
        )
    saved = _install_google_stub(response_factory=response_factory)
    try:
        sys.modules.pop("vocab_builder.llm_client", None)
        sys.modules.pop("llm_client", None)
        llm_client = importlib.import_module("vocab_builder.llm_client")
        llm_client = importlib.reload(llm_client)

        client = llm_client.GeminiClient()
        stream = client.stream("prompt")

        chunks = []
        while True:
            try:
                chunks.append(next(stream))
            except StopIteration as stop:
                metrics = stop.value
                break

        assert "".join(chunks) == "helloworld"
        assert metrics["usage"]["prompt_tokens"] == 11
        assert metrics["usage"]["output_tokens"] == 23
        assert metrics["usage"]["total_tokens"] == 34
        assert metrics["usage"]["thoughts_tokens"] == 5
        assert metrics["tokens_out"] == 23
        assert metrics["usage"].get("tool_tokens") is None
        assert client._client.models.last_count_kwargs is None
    finally:
        _restore_google_stub(saved)
