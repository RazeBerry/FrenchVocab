"""Tests for the Update API Key mechanism.

This module tests the complete flow of updating an API key:
- ProviderManager.update_key()
- LLMCoordinator.update_api_key_interactive()
- Integration with translators reinitialization
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vocab_builder.core.providers import manager as manager_module
from vocab_builder.core.providers.manager import (
    ProviderManager,
    _get_provider_metadata,
)


class StubUI:
    """Stub UI for testing without real terminal interaction."""

    def __init__(self, api_key_inputs=None, confirm_responses=None):
        self._api_key_inputs = list(api_key_inputs or [])
        self._confirm_responses = list(confirm_responses or [])
        self.messages = {"success": [], "warning": [], "error": [], "info": []}
        self.panels = []

    def panel(self, content, title=None, border_style=None, expand=False):
        self.panels.append({"content": content, "title": title, "border_style": border_style})

    def success(self, message, with_panel=False):
        self.messages["success"].append(message)

    def warning(self, message, with_panel=False):
        self.messages["warning"].append(message)

    def error(self, message, with_panel=False):
        self.messages["error"].append(message)

    def info(self, message, with_panel=False):
        self.messages["info"].append(message)

    def confirm(self, message, default=False):
        if self._confirm_responses:
            return self._confirm_responses.pop(0)
        return default

    def prompt(self, *args, **kwargs):
        return ""

    def interactive_menu(self, title, options, instructions=None, show_keys=False):
        return options[0][0] if options else None


def make_manager(tmp_path: Path, ui: StubUI = None) -> tuple:
    """Create a ProviderManager with test configuration."""
    ui = ui or StubUI()
    manager = ProviderManager(ui=ui, project_root=tmp_path)
    return manager, ui


# =============================================================================
# Test: Successful key update with keyring storage
# =============================================================================

class TestUpdateKeyWithKeyring:
    """Tests for successful API key update stored in keyring."""

    def test_update_key_success_stores_in_keyring(self, tmp_path, monkeypatch):
        """Verify that a valid new key is stored in system keyring."""
        ui = StubUI()
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")
        new_key = "AIza" + "x" * 36

        # Mock getpass to return the new key
        monkeypatch.setattr("getpass.getpass", lambda _prompt: new_key)

        # Mock successful validation
        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(return_value=None)

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client

            result = manager.update_key(metadata)

        assert result is not None
        assert result.api_key == new_key
        assert result.metadata.identifier == "gemini"
        assert os.environ.get("GEMINI_API_KEY") == new_key

        # Verify keyring storage was attempted
        success_msgs = " ".join(ui.messages["success"])
        assert "keychain" in success_msgs.lower() or "keyring" in success_msgs.lower()

    def test_update_key_sets_environment_variable(self, tmp_path, monkeypatch):
        """Verify that os.environ is updated with the new key."""
        ui = StubUI()
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")
        new_key = "AIza" + "y" * 36

        # Clear any existing key
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        monkeypatch.setattr("getpass.getpass", lambda _prompt: new_key)

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(return_value=None)

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client

            result = manager.update_key(metadata)

        assert result is not None
        assert os.environ["GEMINI_API_KEY"] == new_key


# =============================================================================
# Test: Fallback to .env file when keyring unavailable
# =============================================================================

class TestUpdateKeyFallbackToEnvFile:
    """Tests for API key update falling back to .env storage."""

    def test_update_key_falls_back_to_env_file(self, tmp_path, monkeypatch):
        """Verify fallback to .env file when keyring fails."""
        ui = StubUI()
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")
        new_key = "AIza" + "z" * 36

        monkeypatch.setattr("getpass.getpass", lambda _prompt: new_key)

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(return_value=None)

        # Make keyring fail
        from keyring.errors import KeyringError

        def _fail_keyring(*args, **kwargs):
            raise KeyringError("Keyring unavailable")

        monkeypatch.setattr(manager_module, "set_password", _fail_keyring)

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client

            result = manager.update_key(metadata)

        assert result is not None
        assert result.api_key == new_key

        # Verify .env file was created
        env_path = tmp_path / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        assert f"GEMINI_API_KEY={new_key}" in content

        # Verify warning about keyring failure
        warnings = " ".join(ui.messages["warning"])
        assert "keychain" in warnings.lower() or "keyring" in warnings.lower()

    def test_update_key_env_file_updates_existing_key(self, tmp_path, monkeypatch):
        """Verify that existing .env key is updated, not duplicated."""
        ui = StubUI()
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        # Create existing .env with old key
        env_path = tmp_path / ".env"
        old_key = "AIza" + "old_" + "x" * 32
        env_path.write_text(f"GEMINI_API_KEY={old_key}\nOTHER_VAR=value\n")

        new_key = "AIza" + "new_" + "y" * 32
        monkeypatch.setattr("getpass.getpass", lambda _prompt: new_key)

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(return_value=None)

        # Disable keyring
        from keyring.errors import KeyringError
        monkeypatch.setattr(manager_module, "set_password", lambda *a, **k: (_ for _ in ()).throw(KeyringError("no")))

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client

            result = manager.update_key(metadata)

        assert result is not None
        content = env_path.read_text()

        # Should have updated key, not duplicated
        assert content.count("GEMINI_API_KEY=") == 1
        assert new_key in content
        assert old_key not in content
        assert "OTHER_VAR=value" in content


# =============================================================================
# Test: Key validation failure (wrong format)
# =============================================================================

class TestUpdateKeyFormatValidation:
    """Tests for API key format validation failures."""

    def test_update_key_rejects_empty_key(self, tmp_path, monkeypatch):
        """Verify that empty key is rejected."""
        ui = StubUI(confirm_responses=[False])
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        calls = {"count": 0}
        inputs = iter(["", "AIza" + "x" * 36])  # first empty, then valid

        def _fake_getpass(_prompt):
            calls["count"] += 1
            return next(inputs)

        monkeypatch.setattr("getpass.getpass", _fake_getpass)

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(return_value=None)

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client
            result = manager.update_key(metadata)

        # Should have prompted again after empty input and eventually succeed
        assert result is not None
        assert calls["count"] >= 2
        assert any("empty" in msg.lower() for msg in ui.messages["warning"])

    def test_update_key_rejects_wrong_prefix(self, tmp_path, monkeypatch):
        """Verify that key with wrong prefix is rejected."""
        ui = StubUI(confirm_responses=[False])  # Don't retry
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        # Key with wrong prefix (OpenAI-style instead of Gemini)
        wrong_key = "sk-" + "x" * 48
        monkeypatch.setattr("getpass.getpass", lambda _prompt: wrong_key)

        result = manager.update_key(metadata)

        assert result is None

        # Verify validation failure was displayed
        assert any("AIza" in p["content"] for p in ui.panels if p.get("content"))

    def test_update_key_rejects_too_short_key(self, tmp_path, monkeypatch):
        """Verify that key that's too short is rejected."""
        ui = StubUI(confirm_responses=[False])
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        short_key = "AIza" + "x" * 10  # Too short (min is 32)
        monkeypatch.setattr("getpass.getpass", lambda _prompt: short_key)

        result = manager.update_key(metadata)

        assert result is None

        # Check that "too short" message appeared
        panels_content = " ".join(p.get("content", "") for p in ui.panels)
        assert "short" in panels_content.lower()


# =============================================================================
# Test: Key validation failure (connection test fails)
# =============================================================================

class TestUpdateKeyConnectionValidation:
    """Tests for API key connection validation failures."""

    def test_update_key_rejects_invalid_credentials(self, tmp_path, monkeypatch):
        """Verify that key failing connection test is rejected."""
        ui = StubUI(confirm_responses=[False])
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        valid_format_key = "AIza" + "x" * 36
        monkeypatch.setattr("getpass.getpass", lambda _prompt: valid_format_key)

        # Mock client that fails verification
        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(
            side_effect=RuntimeError("Invalid API key")
        )

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client

            result = manager.update_key(metadata)

        assert result is None

        # Verify error was shown
        panels_content = " ".join(p.get("content", "") for p in ui.panels)
        assert "invalid" in panels_content.lower() or "failed" in panels_content.lower()

    def test_update_key_handles_timeout(self, tmp_path, monkeypatch):
        """Verify that connection timeout is handled gracefully."""
        ui = StubUI(confirm_responses=[False])
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        valid_format_key = "AIza" + "x" * 36
        monkeypatch.setattr("getpass.getpass", lambda _prompt: valid_format_key)

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(
            side_effect=TimeoutError("Connection timed out")
        )

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client

            result = manager.update_key(metadata)

        assert result is None

        panels_content = " ".join(p.get("content", "") for p in ui.panels)
        assert "timeout" in panels_content.lower() or "timed out" in panels_content.lower()

    def test_update_key_handles_leaked_key_error(self, tmp_path, monkeypatch):
        """Verify that leaked/revoked key error is shown clearly."""
        ui = StubUI(confirm_responses=[False])
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        valid_format_key = "AIza" + "x" * 36
        monkeypatch.setattr("getpass.getpass", lambda _prompt: valid_format_key)

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(
            side_effect=RuntimeError("API key has been leaked and revoked")
        )

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client

            result = manager.update_key(metadata)

        assert result is None


# =============================================================================
# Test: User cancellation (Ctrl+C / KeyboardInterrupt)
# =============================================================================

class TestUpdateKeyCancellation:
    """Tests for user cancellation during key update."""

    def test_update_key_handles_keyboard_interrupt(self, tmp_path, monkeypatch):
        """Verify that Ctrl+C during input is handled gracefully."""
        ui = StubUI()
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        def _raise_interrupt(_prompt):
            raise KeyboardInterrupt()

        monkeypatch.setattr("getpass.getpass", _raise_interrupt)

        with pytest.raises(RuntimeError, match="aborted"):
            manager.update_key(metadata)

    def test_update_key_handles_eof_error(self, tmp_path, monkeypatch):
        """Verify that EOF during input is handled gracefully."""
        ui = StubUI()
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        def _raise_eof(_prompt):
            raise EOFError()

        monkeypatch.setattr("getpass.getpass", _raise_eof)

        with pytest.raises(RuntimeError, match="aborted"):
            manager.update_key(metadata)


# =============================================================================
# Test: Old client is replaced with new client
# =============================================================================

class TestUpdateKeyClientReplacement:
    """Tests for verifying old LLM client is replaced."""

    def test_llm_coordinator_replaces_client_on_update(self, tmp_path, monkeypatch):
        """Verify LLMCoordinator creates new client after key update."""
        from vocab_builder.core.llm_coordinator import LLMCoordinator

        ui = StubUI()
        new_key = "AIza" + "x" * 36
        monkeypatch.setattr("getpass.getpass", lambda _prompt: new_key)

        # Create coordinator with initial (fake) client
        old_client = MagicMock()
        old_client.model_label.return_value = "Old Client"
        old_client.verify_credentials = MagicMock(return_value=None)

        new_client = MagicMock()
        new_client.model_label.return_value = "New Client"
        new_client.verify_credentials = MagicMock(return_value=None)

        coordinator = LLMCoordinator(ui=ui, project_root=tmp_path)
        coordinator._client = old_client
        coordinator._api_available = True
        coordinator._provider_metadata = _get_provider_metadata("gemini")

        # Track client creation
        clients_created = []

        def _track_create(provider, api_key=None):
            client = MagicMock()
            client.verify_credentials = MagicMock(return_value=None)
            client.model_label.return_value = f"Client for {api_key[:8] if api_key else 'env'}..."
            clients_created.append((provider, api_key))
            return client

        with patch("vocab_builder.llm_client.ProviderFactory.create", side_effect=_track_create):
            with patch.object(manager_module, "ProviderFactory") as mock_factory:
                mock_factory.create.return_value = new_client

                result = coordinator.update_api_key_interactive()

        assert result is True
        assert coordinator._client is not old_client
        assert coordinator._api_available is True

    def test_update_preserves_provider_metadata(self, tmp_path, monkeypatch):
        """Verify provider metadata is preserved after key update."""
        from vocab_builder.core.llm_coordinator import LLMCoordinator

        ui = StubUI()
        new_key = "AIza" + "x" * 36
        monkeypatch.setattr("getpass.getpass", lambda _prompt: new_key)

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(return_value=None)

        coordinator = LLMCoordinator(ui=ui, project_root=tmp_path)
        coordinator._provider_metadata = _get_provider_metadata("gemini")
        coordinator._client = MagicMock()
        coordinator._api_available = True

        with patch("vocab_builder.llm_client.ProviderFactory.create", return_value=mock_client):
            with patch.object(manager_module, "ProviderFactory") as mock_factory:
                mock_factory.create.return_value = mock_client

                coordinator.update_api_key_interactive()

        assert coordinator._provider_metadata.identifier == "gemini"
        assert coordinator._provider_metadata.env_var == "GEMINI_API_KEY"


# =============================================================================
# Test: Translators are reinitialized
# =============================================================================

class TestUpdateKeyTranslatorReinit:
    """Tests for verifying translators are reinitialized after key update."""

    def test_on_success_callback_is_invoked(self, tmp_path, monkeypatch):
        """Verify that on_success callback is called after successful update."""
        from vocab_builder.core.llm_coordinator import LLMCoordinator

        ui = StubUI()
        new_key = "AIza" + "x" * 36
        monkeypatch.setattr("getpass.getpass", lambda _prompt: new_key)

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(return_value=None)

        coordinator = LLMCoordinator(ui=ui, project_root=tmp_path)
        coordinator._provider_metadata = _get_provider_metadata("gemini")
        coordinator._client = MagicMock()
        coordinator._api_available = True

        callback_invoked = []

        def _callback():
            callback_invoked.append(True)

        with patch("vocab_builder.llm_client.ProviderFactory.create", return_value=mock_client):
            with patch.object(manager_module, "ProviderFactory") as mock_factory:
                mock_factory.create.return_value = mock_client

                coordinator.update_api_key_interactive(on_success=_callback)

        assert len(callback_invoked) == 1

    def test_on_success_not_called_on_failure(self, tmp_path, monkeypatch):
        """Verify that on_success callback is NOT called when update fails."""
        from vocab_builder.core.llm_coordinator import LLMCoordinator

        ui = StubUI(confirm_responses=[False])
        wrong_key = "sk-wrong-prefix" + "x" * 30
        monkeypatch.setattr("getpass.getpass", lambda _prompt: wrong_key)

        coordinator = LLMCoordinator(ui=ui, project_root=tmp_path)
        coordinator._provider_metadata = _get_provider_metadata("gemini")
        coordinator._client = MagicMock()
        coordinator._api_available = True

        callback_invoked = []

        def _callback():
            callback_invoked.append(True)

        coordinator.update_api_key_interactive(on_success=_callback)

        assert len(callback_invoked) == 0


# =============================================================================
# Test: Edge cases and error handling
# =============================================================================

class TestUpdateKeyEdgeCases:
    """Tests for edge cases in API key update."""

    def test_update_key_with_no_provider_configured(self, tmp_path):
        """Verify error when no provider is configured."""
        from vocab_builder.core.llm_coordinator import LLMCoordinator

        ui = StubUI()
        coordinator = LLMCoordinator(ui=ui, project_root=tmp_path)
        coordinator._provider_metadata = None
        coordinator._client = None

        result = coordinator.update_api_key_interactive()

        assert result is False
        assert any("No provider" in msg for msg in ui.messages["error"])

    def test_update_key_for_claude_provider(self, tmp_path, monkeypatch):
        """Verify update flow works for Claude provider."""
        ui = StubUI()
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("claude")
        new_key = "sk-ant-" + "x" * 95

        monkeypatch.setattr("getpass.getpass", lambda _prompt: new_key)

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(return_value=None)

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client

            result = manager.update_key(metadata)

        assert result is not None
        assert result.api_key == new_key
        assert os.environ.get("ANTHROPIC_API_KEY") == new_key

    def test_update_key_displays_correct_panel_title(self, tmp_path, monkeypatch):
        """Verify the update panel shows correct provider info."""
        ui = StubUI(confirm_responses=[False])
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        # Use wrong format to trigger failure path (to see panel)
        monkeypatch.setattr("getpass.getpass", lambda _prompt: "wrong")

        manager.update_key(metadata)

        # Check that "Update API Key" panel was shown
        panel_titles = [p.get("title", "") for p in ui.panels]
        assert "Update API Key" in panel_titles

    def test_update_key_shows_doc_url(self, tmp_path, monkeypatch):
        """Verify the documentation URL is displayed."""
        ui = StubUI(confirm_responses=[False])
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        monkeypatch.setattr("getpass.getpass", lambda _prompt: "short")

        manager.update_key(metadata)

        # Check that doc URL was shown in panel
        panels_content = " ".join(p.get("content", "") for p in ui.panels)
        assert "ai.google.dev" in panels_content


# =============================================================================
# Test: Retry mechanism
# =============================================================================

class TestUpdateKeyRetry:
    """Tests for the retry mechanism on validation failure."""

    def test_update_key_allows_retry_on_failure(self, tmp_path, monkeypatch):
        """Verify user can retry after entering wrong key."""
        ui = StubUI(confirm_responses=[True])  # Confirm retry
        manager, _ = make_manager(tmp_path, ui)
        metadata = _get_provider_metadata("gemini")

        # First attempt: wrong key, second attempt: correct key
        attempts = iter(["wrong_key", "AIza" + "x" * 36])
        monkeypatch.setattr("getpass.getpass", lambda _prompt: next(attempts))

        mock_client = MagicMock()
        mock_client.verify_credentials = MagicMock(return_value=None)

        with patch.object(manager_module, "ProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_client

            result = manager.update_key(metadata)

        # Should succeed on second attempt
        assert result is not None
        assert result.api_key == "AIza" + "x" * 36
