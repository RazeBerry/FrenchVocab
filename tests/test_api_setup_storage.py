from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent))
from _stubs import install_basic_stubs  # type: ignore


install_basic_stubs()

import FrenchVocab  # noqa: E402
import core.vocab as vocab_module  # noqa: E402


class _StubUI:
    def __init__(self, choices):
        self._choices = list(choices)
        self.messages = {"success": [], "warning": [], "error": [], "info": []}

    def interactive_menu(self, _title, options, _instructions, show_keys=False):  # noqa: ARG002
        if not self._choices:
            return options[0][0]
        return self._choices.pop(0)

    def success(self, message, with_panel=False):  # noqa: ARG002
        self.messages["success"].append(message)

    def warning(self, message, with_panel=False):  # noqa: ARG002
        self.messages["warning"].append(message)

    def error(self, message, with_panel=False):  # noqa: ARG002
        self.messages["error"].append(message)

    def info(self, message, with_panel=False):  # noqa: ARG002
        self.messages["info"].append(message)

    def panel(self, *_args, **_kwargs):  # pragma: no cover - unused in tests
        pass


def _make_builder(tmp_path: Path):
    builder = object.__new__(vocab_module.FrenchVocabBuilder)
    builder.project_root = tmp_path
    builder.ui = _StubUI([])
    return builder


def test_store_api_key_writes_env_file(tmp_path):
    builder = _make_builder(tmp_path)
    builder.ui._choices = ["env_file"]
    metadata = vocab_module._get_provider_metadata("gemini")

    result = vocab_module.FrenchVocabBuilder._store_api_key(builder, metadata, "AIza" + "x" * 36)

    assert result.startswith(".env")
    env_path = tmp_path / ".env"
    assert env_path.exists()
    content = env_path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=AIza" in content
    warnings = builder.ui.messages["warning"]
    assert any("Run FrenchVocab" in msg for msg in warnings)


def test_store_api_key_keyring_failure_falls_back(tmp_path, monkeypatch):
    builder = _make_builder(tmp_path)
    # first attempt keyring (fail), second attempt env_file
    builder.ui._choices = ["keyring", "env_file"]
    metadata = vocab_module._get_provider_metadata("gemini")

    import keyring
    from keyring.errors import KeyringError

    def _fail(*_args, **_kwargs):
        raise KeyringError("backend missing")

    monkeypatch.setattr(keyring, "set_password", _fail)
    monkeypatch.setattr(vocab_module.keyring, "set_password", _fail)

    result = vocab_module.FrenchVocabBuilder._store_api_key(builder, metadata, "AIza" + "x" * 36)

    assert result.startswith(".env")
    warnings = "\n".join(builder.ui.messages["warning"])
    assert "Keyring is not available" in warnings
    assert (tmp_path / ".env").exists()
