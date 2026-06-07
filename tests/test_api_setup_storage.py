import os
import stat
from pathlib import Path

from vocab_builder.core.providers import manager as manager_module
from vocab_builder.core.providers.manager import ProviderManager, _get_provider_metadata


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


def test_store_api_key_missing_keyring_module_falls_back_to_env_file(tmp_path, monkeypatch):
    manager, ui = _make_manager(tmp_path, choices=["keyring", "env_file"])
    metadata = _get_provider_metadata("gemini")

    def _missing_keyring(*_args, **_kwargs):
        raise ModuleNotFoundError("No module named 'keyring'")

    monkeypatch.setattr(manager_module, "set_password", _missing_keyring)

    result = manager._store_api_key(metadata, "AIza" + "m" * 36)

    assert result.startswith(".env")
    assert (tmp_path / ".env").exists()
    warnings = "\n".join(ui.messages["warning"])
    assert "Keyring is not available" in warnings


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


def test_resolve_api_key_handles_missing_keyring_module(tmp_path, monkeypatch):
    manager, ui = _make_manager(tmp_path)
    metadata = _get_provider_metadata("gemini")
    monkeypatch.delenv(metadata.env_var, raising=False)

    def _missing_keyring(*_args, **_kwargs):
        raise ModuleNotFoundError("No module named 'keyring'")

    monkeypatch.setattr(manager_module, "get_password", _missing_keyring)

    api_key, source = manager._resolve_api_key(metadata)

    assert api_key is None
    assert source is None
    assert any("Error accessing system keyring" in msg for msg in ui.messages["error"])


def test_store_api_key_respects_config_dir_env(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("VOCABBUILDER_SKIP_KEYRING", "1")

    manager, _ = _make_manager(tmp_path)
    metadata = _get_provider_metadata("gemini")

    storage = manager._store_api_key_to_keyring(metadata, "AIza" + "x" * 36)

    env_path = cfg_dir / ".env"
    assert env_path.exists()
    assert "GEMINI_API_KEY=AIza" in env_path.read_text(encoding="utf-8")
    assert storage.startswith(".env")


def test_resolve_api_key_reads_legacy_keyring_service(tmp_path, monkeypatch):
    manager, _ = _make_manager(tmp_path)
    metadata = _get_provider_metadata("gemini")
    api_key = "AIza" + "k" * 36

    monkeypatch.delenv(metadata.env_var, raising=False)

    import keyring

    keyring._store.clear()
    keyring.set_password("french_vocab_builder", metadata.keyring_name, api_key)

    resolved, source = manager._resolve_api_key(metadata)

    assert resolved == api_key
    assert source == "system keyring"
    assert keyring.get_password("vocab_builder", metadata.keyring_name) == api_key


def test_prepare_provider_reads_legacy_env_file_after_new_dir_exists(tmp_path, monkeypatch):
    manager, _ = _make_manager(tmp_path)
    metadata = _get_provider_metadata("gemini")
    old_dir = tmp_path / ".frenchvocab"
    new_dir = tmp_path / ".vocabbuilder"
    old_dir.mkdir()
    new_dir.mkdir()
    env_value = "AIza" + "z" * 36
    legacy_env = old_dir / ".env"
    (new_dir / ".env").write_text("UNRELATED_VALUE=1\n", encoding="utf-8")
    legacy_env.write_text(f"{metadata.env_var}={env_value}\n", encoding="utf-8")

    monkeypatch.delenv(metadata.env_var, raising=False)
    monkeypatch.setattr(manager, "_candidate_env_paths", lambda: (new_dir / ".env", legacy_env))

    resolution = manager.prepare_provider(metadata)

    assert resolution.api_key == env_value
    assert os.environ[metadata.env_var] == env_value


def test_write_env_file_hardens_permissions_and_removes_stale_backup(tmp_path):
    manager, _ = _make_manager(tmp_path)
    metadata = _get_provider_metadata("gemini")
    env_path = tmp_path / ".env"
    backup_path = tmp_path / ".env.bak"

    env_path.write_text("GEMINI_API_KEY=old\n", encoding="utf-8")
    backup_path.write_text("GEMINI_API_KEY=older\n", encoding="utf-8")

    storage = manager._write_env_file(metadata, "AIza" + "p" * 36)

    assert storage is not None
    assert env_path.exists()
    assert not backup_path.exists()
    if os.name != "nt":
        mode = stat.S_IMODE(env_path.stat().st_mode)
        assert mode == 0o600


def test_write_env_file_updates_export_assignment_without_duplicate(tmp_path):
    manager, _ = _make_manager(tmp_path)
    metadata = _get_provider_metadata("gemini")
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# GEMINI_API_KEY=commented\n"
        "export GEMINI_API_KEY=old\n"
        "OTHER_VAR=value\n",
        encoding="utf-8",
    )

    storage = manager._write_env_file(metadata, "AIza" + "q" * 36)

    assert storage is not None
    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "# GEMINI_API_KEY=commented",
        "export GEMINI_API_KEY=AIza" + "q" * 36,
        "OTHER_VAR=value",
    ]
