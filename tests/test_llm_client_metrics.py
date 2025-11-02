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
    def __init__(self):
        self.last_count_kwargs = None

    def generate_content_stream(self, **_kwargs):
        return _FakeStream()

    def count_tokens(self, **kwargs):
        self.last_count_kwargs = kwargs
        return SimpleNamespace(total_tokens=5)


class _Client:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.models = _Models()


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


def _install_google_stub():
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

    genai_mod.Client = _Client
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
        chunks = list(client.stream("prompt"))
        assert "".join(chunks) == "helloworld"

        models = client._client.models
        payload = models.last_count_kwargs["contents"]
        assert isinstance(payload, list)
        assert len(payload) == 1
        content = payload[0]
        assert getattr(content, "role", None) == "user"
        assert content.parts[0]["text"] == "helloworld"
    finally:
        _restore_google_stub(saved)
