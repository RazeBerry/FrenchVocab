import importlib.util
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace


class _FakeStream:
    def __init__(self):
        self._iterator = iter([SimpleNamespace(text="hello"), SimpleNamespace(text="world")])

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iterator)


class _Models:
    def __init__(self, stream_factory=None):
        self.last_count_kwargs = None
        self._stream_factory = stream_factory or _FakeStream

    def generate_content_stream(self, **_kwargs):
        return self._stream_factory()

    def count_tokens(self, **kwargs):
        self.last_count_kwargs = kwargs
        return SimpleNamespace(total_tokens=5)


class _Client:
    def __init__(self, api_key=None, stream_factory=None):
        self.api_key = api_key
        self.models = _Models(stream_factory)


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


def _install_google_stub(stream_factory=None):
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

    genai_mod.Client = lambda api_key=None: _Client(api_key=api_key, stream_factory=stream_factory)
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


def test_gemini_client_uses_structured_token_payload(tmp_path):
    os.environ["GEMINI_API_KEY"] = "AIza" + "x" * 36
    saved = _install_google_stub()
    try:
        module_path = Path(__file__).resolve().parent.parent / "llm_client.py"
        spec = importlib.util.spec_from_file_location("llm_client_actual", module_path)
        llm_client = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(llm_client)

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
        payload = models.last_count_kwargs["contents"]
        assert isinstance(payload, list)
        assert len(payload) == 1
        content = payload[0]
        assert getattr(content, "role", None) == "user"
        assert content.parts[0]["text"] == "helloworld"
        assert metrics["usage"]["output_tokens"] == 5
        assert metrics["usage"]["total_tokens"] == 5
    finally:
        _restore_google_stub(saved)


def test_gemini_client_reports_usage_metadata(tmp_path):
    os.environ["GEMINI_API_KEY"] = "AIza" + "x" * 36

    def stream_factory():
        stream = _FakeStream()
        stream.response = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=11,
                candidates_token_count=23,
                total_token_count=34,
                thoughts_token_count=5,
                tool_use_prompt_token_count=None,
                cached_content_token_count=None,
            )
        )
        return stream

    saved = _install_google_stub(stream_factory=stream_factory)
    try:
        module_path = Path(__file__).resolve().parent.parent / "llm_client.py"
        spec = importlib.util.spec_from_file_location("llm_client_actual", module_path)
        llm_client = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(llm_client)

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
