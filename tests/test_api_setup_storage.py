import os
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent))
from _stubs import install_basic_stubs  # type: ignore


install_basic_stubs()

import FrenchVocab  # noqa: E402,F401
from core.providers import manager as manager_module  # noqa: E402
from core.providers.manager import ProviderManager, _get_provider_metadata  # noqa: E402


class _StubUI:
    def __init__(self, choices=None):
        self._choices = list(choices or [])
        self.messages = {"success": [], "warning": [], "error": [], "info": []}

    def interactive_menu(self, _title, options, _instructions=None, show_keys=False):  # noqa: ARG002
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

    def panel(self, *_args, **_kwargs):  # pragma: no cover - unused here
        pass

    def confirm(self, _message, default=False):  # noqa: ARG002
        return default

    def prompt(self, *_args, **_kwargs):  # pragma: no cover - unused here
        return ""


def _make_manager(tmp_path: Path, choices=None):
    ui = _StubUI(choices)
    mgr = ProviderManager(ui=ui, project_root=tmp_path)
    return mgr, ui


def test_store_api_key_writes_env_file(tmp_path):
    manager, ui = _make_manager(tmp_path, choices=["env_file"])
    metadata = _get_provider_metadata("gemini")

    result = manager._store_api_key(metadata, "AIza" + "x" * 36)

    assert result.startswith(".env")
    env_path = tmp_path / ".env"
    assert env_path.exists()
    content = env_path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=AIza" in content
    info_messages = ui.messages["info"]
    assert any("Future runs will automatically reuse this key" in msg for msg in info_messages)


def test_store_api_key_keyring_failure_falls_back(tmp_path, monkeypatch):
    manager, ui = _make_manager(tmp_path, choices=["keyring", "env_file"])
    metadata = _get_provider_metadata("gemini")

    import keyring
    from keyring.errors import KeyringError

    def _fail(*_args, **_kwargs):
        raise KeyringError("backend missing")

    monkeypatch.setattr(keyring, "set_password", _fail)
    monkeypatch.setattr(manager_module, "set_password", _fail)

    result = manager._store_api_key(metadata, "AIza" + "x" * 36)

    assert result.startswith(".env")
    warnings = "\n".join(ui.messages["warning"])
    assert "Keyring is not available" in warnings
    assert (tmp_path / ".env").exists()


def test_prepare_provider_reads_env_file(tmp_path, monkeypatch):
    manager, ui = _make_manager(tmp_path)
    metadata = _get_provider_metadata("gemini")

    env_value = "AIza" + "x" * 36
    (tmp_path / ".env").write_text(f"{metadata.env_var}={env_value}\n", encoding="utf-8")

    monkeypatch.delenv(metadata.env_var, raising=False)

    resolution = manager.prepare_provider(metadata)

    assert os.environ[metadata.env_var] == env_value
    assert resolution.metadata.identifier == metadata.identifier
    info_messages = ui.messages["info"]
    assert any("Loaded environment variables" in msg for msg in info_messages)
    success_messages = ui.messages["success"]
    assert any(metadata.display_name in msg for msg in success_messages)
    monkeypatch.delenv(metadata.env_var, raising=False)


def test_store_api_key_respects_config_dir_env(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("FRENCHVOCAB_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("FRENCHVOCAB_SKIP_KEYRING", "1")

    manager, _ = _make_manager(tmp_path)
    metadata = _get_provider_metadata("gemini")

    storage = manager._store_api_key_to_keyring(metadata, "AIza" + "x" * 36)

    env_path = cfg_dir / ".env"
    assert env_path.exists()
    assert "GEMINI_API_KEY=AIza" in env_path.read_text(encoding="utf-8")
    assert storage.startswith(".env")
