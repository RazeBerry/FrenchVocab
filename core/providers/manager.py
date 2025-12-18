import getpass
import os
import shutil
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from keyring import get_password, set_password  # type: ignore[import]
from keyring.errors import KeyringError  # type: ignore[import]

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency should be present in runtime
    load_dotenv = None  # type: ignore[misc,assignment]

from llm_client import ProviderFactory
from ui_helper import UIHelper


@dataclass(frozen=True)
class ProviderMetadata:
    identifier: str
    env_var: str
    keyring_name: str
    display_name: str
    doc_url: str
    key_prefixes: Tuple[str, ...]
    min_length: int = 32


@dataclass(frozen=True)
class ValidationFeedback:
    valid: bool
    message: str
    suggestions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderResolution:
    metadata: ProviderMetadata
    api_key: str
    source: Optional[str]


_PROVIDER_REGISTRY: Dict[str, ProviderMetadata] = {
    "gemini": ProviderMetadata(
        identifier="gemini",
        env_var="GEMINI_API_KEY",
        keyring_name="gemini_api_key",
        display_name="Google Gemini",
        doc_url="https://ai.google.dev/",
        key_prefixes=("AIza",),
        min_length=32,
    ),
    "claude": ProviderMetadata(
        identifier="claude",
        env_var="ANTHROPIC_API_KEY",
        keyring_name="anthropic_api_key",
        display_name="Anthropic Claude",
        doc_url="https://console.anthropic.com/",
        key_prefixes=("sk-ant-",),
        min_length=40,
    ),
}


def _get_provider_metadata(provider: Optional[str]) -> ProviderMetadata:
    if not provider:
        return _PROVIDER_REGISTRY["gemini"]

    key = provider.lower()
    metadata = _PROVIDER_REGISTRY.get(key)
    if metadata is None:
        available = ", ".join(sorted(_PROVIDER_REGISTRY.keys()))
        raise ValueError(
            f"Unknown provider '{provider}'. Available providers: {available}."
        )
    return metadata


class ProviderManager:
    """Encapsulates provider configuration, credential storage, and validation."""

    def __init__(self, ui: UIHelper, project_root: Path):
        self.ui = ui
        self.project_root = Path(project_root)
        self._env_path = self._determine_env_path(self.project_root)
        # Allow skipping keyring probing for faster startup in CI/containers.
        skip = os.environ.get("FRENCHVOCAB_SKIP_KEYRING", "")
        self._keyring_enabled = str(skip).strip().lower() not in {"1", "true", "yes", "y"}

    # Public API ---------------------------------------------------------
    def get_metadata(self, provider: Optional[str]) -> ProviderMetadata:
        return _get_provider_metadata(provider)

    def available_providers(self) -> Iterable[ProviderMetadata]:
        return _PROVIDER_REGISTRY.values()

    # Helper: decide where to read/write the .env file
    def _determine_env_path(self, project_root: Path) -> Path:
        """Choose a writable .env location, preferring project root, with fallbacks.

        Order of preference:
        1) FRENCHVOCAB_CONFIG_DIR/.env (explicit override)
        2) project_root/.env if writable
        3) ~/.frenchvocab/.env
        """

        # 1) Explicit override for tests or custom deployments
        env_dir_override = os.environ.get("FRENCHVOCAB_CONFIG_DIR")
        if env_dir_override:
            env_dir = Path(env_dir_override).expanduser()
            try:
                env_dir.mkdir(parents=True, exist_ok=True)
                return env_dir / ".env"
            except OSError as exc:  # pragma: no cover - defensive
                self.ui.warning(f"Failed to create config dir {env_dir}: {exc}. Falling back to defaults.")

        # 2) Project root, if writable
        project_env = Path(project_root) / ".env"
        project_parent = project_env.parent
        if project_env.exists():
            if project_env.is_file() and os.access(project_env, os.W_OK):
                return project_env
        else:
            if os.access(project_parent, os.W_OK):
                return project_env

        # 3) User config dir (always attempt to create)
        fallback_dir = Path.home() / ".frenchvocab"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir / ".env"

    def prepare_provider(self, metadata: ProviderMetadata) -> ProviderResolution:
        """Ensure an API key exists for the given provider, prompting if needed."""
        self._load_env_file()

        api_key, source = self._resolve_api_key(metadata)
        if not api_key:
            metadata, api_key = self._run_setup_wizard(metadata)
            source = "interactive setup"

        os.environ[metadata.env_var] = api_key
        origin = source or "configuration"
        self.ui.success(f"{metadata.display_name} API key ready ({origin}).")
        return ProviderResolution(metadata=metadata, api_key=api_key, source=source)

    def resolve_provider_silently(self, metadata: ProviderMetadata) -> Optional[ProviderResolution]:
        """Attempt non-interactive credential resolution (env/keyring only).

        Returns None when credentials are missing or invalid, so callers can
        decide whether to fall back to interactive flows.
        """
        self._load_env_file()
        api_key, source = self._resolve_api_key(metadata)
        if not api_key:
            return None
        return ProviderResolution(metadata=metadata, api_key=api_key, source=source)

    def change_provider(self, current: ProviderMetadata) -> Optional[ProviderResolution]:
        """Interactive provider switcher; returns new credentials or None on cancel."""
        metadata = self._prompt_for_provider(current)
        api_key, source = self._resolve_api_key(metadata)
        if not api_key:
            try:
                metadata, api_key = self._run_setup_wizard(metadata)
            except RuntimeError as exc:
                self.ui.error(str(exc) or "API setup aborted by user.")
                return None
            source = "interactive setup"

        os.environ[metadata.env_var] = api_key
        return ProviderResolution(metadata=metadata, api_key=api_key, source=source)

    def update_key(self, metadata: ProviderMetadata) -> Optional[ProviderResolution]:
        """Prompt the user for a new API key for the given provider."""
        self.ui.panel(
            f"Updating API key for [bold]{metadata.display_name}[/bold]\n\n"
            f"Get a new key at: {metadata.doc_url}",
            title="Update API Key",
            border_style="yellow",
        )

        while True:
            api_key = self._prompt_for_api_key(metadata)
            validation = self._validate_api_key(metadata, api_key, perform_connection_test=True)

            if validation.valid:
                break

            self._display_validation_failure(metadata, validation)
            if not self.ui.confirm("Try entering the key again?", default=True):
                return None

        storage = self._store_api_key_to_keyring(metadata, api_key)
        os.environ[metadata.env_var] = api_key
        self.ui.info(f"Key stored via {storage}.")
        return ProviderResolution(metadata=metadata, api_key=api_key, source=storage)

    def validate_connection(self, metadata: ProviderMetadata, api_key: str) -> ValidationFeedback:
        return self._validate_with_provider(metadata, api_key)

    # Private helpers ----------------------------------------------------
    def _load_env_file(self) -> Optional[Path]:
        env_path = self._env_path
        if load_dotenv is None:
            if env_path.exists():
                self.ui.warning(
                    "python-dotenv is not installed; skipping automatic .env loading."
                )
            return None

        if not env_path.exists():
            return None

        try:
            loaded = load_dotenv(dotenv_path=env_path, override=False)
        except Exception as exc:
            self.ui.warning(f"Failed to load {env_path}: {exc}")
            return None

        if loaded:
            self.ui.info(f"Loaded environment variables from {env_path}.")
            return env_path
        return None

    def _resolve_api_key(self, metadata: ProviderMetadata) -> Tuple[Optional[str], Optional[str]]:
        # Prefer persisted credentials (keyring) over ambient environment variables so that
        # a stray exported key cannot silently override the saved one.
        stored_key = None
        if self._keyring_enabled:
            try:
                stored_key = get_password("french_vocab_builder", metadata.keyring_name)
            except KeyringError as exc:
                self.ui.error(f"Error accessing system keyring: {exc}")

        if stored_key:
            result = self._validate_api_key(metadata, stored_key, perform_connection_test=False)
            if result.valid:
                os.environ.setdefault(metadata.env_var, stored_key)
                return stored_key, "system keyring"
            self.ui.warning(
                "Stored keyring credential failed validation; starting setup wizard."
            )

        env_value = os.environ.get(metadata.env_var)
        if env_value:
            result = self._validate_api_key(metadata, env_value, perform_connection_test=False)
            if result.valid:
                self.ui.warning(
                    f"Found {metadata.env_var} in environment; using it for this session. "
                    "Saved keyring/.env credentials are ignored until you unset it."
                )
                return env_value, "environment variable"
            self.ui.warning(
                f"Ignoring invalid {metadata.env_var} from environment: {result.message}"
            )

        return None, None

    def _run_setup_wizard(self, default_metadata: ProviderMetadata) -> Tuple[ProviderMetadata, str]:
        self.ui.panel(
            "[bold cyan]🚀 Welcome to FrenchVocab![/bold cyan]\n\n"
            "To translate words, you need an AI provider.\n\n"
            "[bold]Choose your setup experience:[/bold]",
            title="First-Time Setup",
            border_style="cyan",
        )

        options = [
            ("guided", "[bold green]✨ Guided Setup[/bold green] [dim](Recommended for beginners)[/dim]\n   Quick 3-step setup with Google Gemini (free tier available)"),
            ("advanced", "⚙️  Advanced Setup\n   Choose provider, storage method, and more options"),
        ]

        try:
            choice = self.ui.interactive_menu(
                "Setup Mode",
                options,
                "Use ↑ and ↓ to choose. Press Enter to continue.",
                show_keys=False,
            )
        except KeyboardInterrupt as exc:
            raise RuntimeError("API setup aborted by user.") from exc

        if choice == "guided":
            return self._run_guided_onboarding(default_metadata)

        return self._run_advanced_setup_wizard(default_metadata)

    def _run_guided_onboarding(self, default_metadata: ProviderMetadata) -> Tuple[ProviderMetadata, str]:
        metadata = _get_provider_metadata("gemini")

        self.ui.panel(
            "[bold]Step 1/3: Get Your Free API Key[/bold]\n\n"
            "We'll use Google Gemini (free tier: 60 requests/minute).\n\n"
            "[cyan]What you need to do:[/cyan]\n"
            "1. Visit: [bold]https://ai.google.dev/[/bold]\n"
            "2. Click [bold]\"Get API Key\"[/bold] or [bold]\"API Keys\"[/bold]\n"
            "3. Sign in with your Google account\n"
            "4. Click [bold]\"Create API Key\"[/bold]\n"
            "5. Copy the key (starts with [bold]AIza...[/bold])\n\n"
            "✨ [dim]Tip: The key is free and takes ~1 minute to generate![/dim]",
            title="🔑 API Key Needed",
            border_style="blue",
        )

        self.ui.prompt("\nPress Enter when you have your API key ready...")

        while True:
            self.ui.panel(
                "[bold]Step 2/3: Enter Your API Key[/bold]\n\n"
                "Paste your Gemini API key below.\n"
                "[dim]Input is hidden for security.[/dim]",
                title="🔐 Secure Input",
                border_style="yellow",
            )

            api_key = self._prompt_for_api_key(metadata)
            validation = self._validate_api_key(metadata, api_key, perform_connection_test=True)

            if validation.valid:
                break

            self._display_validation_failure(metadata, validation)
            if not self.ui.confirm("Try entering the key again?", default=True):
                raise RuntimeError("API setup aborted by user.")

        self.ui.panel(
            "[bold]Step 3/3: Saving Your Key[/bold]\n\n"
            "We'll store your API key securely, preferring your system keychain.\n"
            "[dim]If the keychain isn't available, we'll fall back to a local .env file or temporary session storage.[/dim]",
            title="💾 Secure Storage",
            border_style="green",
        )

        storage = self._store_api_key_to_keyring(metadata, api_key)

        if storage == "system keyring":
            storage_line = "🔐 Storage: [bold]System Keychain[/bold]"
            persistence_note = "[dim]Tip: Your key is saved - you won't need to enter it again.[/dim]"
        elif storage.startswith(".env"):
            storage_line = f"🔐 Storage: [bold]{storage}[/bold]"
            persistence_note = "[dim]Tip: We'll reuse this .env entry automatically next time.[/dim]"
        else:
            storage_line = "🔐 Storage: [bold]Current session only[/bold]"
            persistence_note = "[yellow]You'll be prompted for the key again the next time you launch FrenchVocab.[/yellow]"
            self.ui.warning(
                "Key stored for this session only. Run the setup again next time to restore AI features."
            )

        self.ui.panel(
            "[bold green]✅ All Set![/bold green]\n\n"
            "Your FrenchVocab is ready to use!\n\n"
            "🎯 Provider: [bold]Google Gemini[/bold]\n"
            f"{storage_line}\n"
            "📚 You can now add vocabulary and translate!\n\n"
            f"{persistence_note}",
            title="🎉 Setup Complete",
            border_style="green",
        )

        return metadata, api_key

    def _run_advanced_setup_wizard(self, default_metadata: ProviderMetadata) -> Tuple[ProviderMetadata, str]:
        self.ui.panel(
            "[bold blue]Advanced Setup Mode[/bold blue]\n\n"
            "You'll be able to choose your AI provider and storage method.",
            title="API Setup",
            border_style="blue",
        )

        metadata = default_metadata
        while True:
            metadata = self._prompt_for_provider(metadata)

            while True:
                api_key = self._prompt_for_api_key(metadata)
                validation = self._validate_api_key(metadata, api_key, perform_connection_test=True)
                if validation.valid:
                    storage = self._store_api_key(metadata, api_key)
                    self.ui.info(f"Key stored via {storage}.")
                    return metadata, api_key

                self._display_validation_failure(metadata, validation)
                if not self.ui.confirm("Try entering the key again?", default=True):
                    break

            if not self.ui.confirm("Choose a different provider?", default=False):
                raise RuntimeError("API setup aborted by user.")

    def _prompt_for_provider(self, current: ProviderMetadata) -> ProviderMetadata:
        options: List[Tuple[str, str]] = []
        for identifier, metadata in _PROVIDER_REGISTRY.items():
            label = metadata.display_name
            if identifier == "gemini":
                label = f"{label} [dim](Recommended)[/dim]"
            if identifier == current.identifier:
                label = f"{label} [dim](current selection)[/dim]"
            options.append((identifier, label))
        options.append(("exit", "Exit setup"))

        try:
            choice = self.ui.interactive_menu(
                "Choose Provider",
                options,
                "Use ↑ and ↓ to highlight a provider. Enter confirms.",
                show_keys=False,
            )
        except KeyboardInterrupt as exc:
            raise RuntimeError("API setup aborted by user.") from exc

        if choice == "exit":
            raise RuntimeError("API setup aborted by user.")

        return _get_provider_metadata(choice)

    def _prompt_for_api_key(self, metadata: ProviderMetadata) -> str:
        instructions = (
            f"[bold]{metadata.display_name} requires an API key.[/bold]\n"
            f"Get yours at: {metadata.doc_url}\n\n"
            "Paste the key below. Input is hidden for safety."
        )
        self.ui.panel(instructions, title=f"{metadata.display_name} Setup", border_style="yellow")

        while True:
            try:
                raw = getpass.getpass(f"Enter your {metadata.display_name} API key: ")
            except (EOFError, KeyboardInterrupt) as exc:
                raise RuntimeError("API setup aborted by user.") from exc

            api_key = raw.strip()
            if api_key:
                return api_key
            self.ui.warning("API key cannot be empty. Please try again.")

    def _validate_api_key(
        self,
        metadata: ProviderMetadata,
        api_key: str,
        *,
        perform_connection_test: bool,
    ) -> ValidationFeedback:
        key = (api_key or "").strip()
        if not key:
            return ValidationFeedback(False, "Key cannot be empty.", ("Paste the full key from the provider dashboard.",))

        if len(key) < metadata.min_length:
            return ValidationFeedback(
                False,
                "Key appears too short.",
                ("Copy the entire key; some providers hide the middle section.",),
            )

        if metadata.key_prefixes and not any(key.startswith(prefix) for prefix in metadata.key_prefixes):
            expected = " or ".join(f"'{p}'" for p in metadata.key_prefixes)
            return ValidationFeedback(
                False,
                f"Doesn't resemble a {metadata.display_name} key.",
                (
                    f"{metadata.display_name} keys typically start with {expected}.",
                    f"Check the provider at {metadata.doc_url} or switch providers.",
                ),
            )

        if not perform_connection_test:
            return ValidationFeedback(True, "Key format looks valid.")

        return self._validate_with_provider(metadata, key)

    def _validate_with_provider(self, metadata: ProviderMetadata, api_key: str) -> ValidationFeedback:
        self.ui.info(f"Testing connection to {metadata.display_name}…")
        try:
            client = ProviderFactory.create(metadata.identifier, api_key)
        except Exception as exc:
            return ValidationFeedback(
                False,
                f"Failed to initialize {metadata.display_name} client: {exc}",
                (
                    f"Ensure the key is active in the {metadata.display_name} console.",
                    f"Generate a new key via {metadata.doc_url} if the issue persists.",
                ),
            )

        verifier = getattr(client, "verify_credentials", None)
        if callable(verifier):
            try:
                verifier(timeout=5.0)
            except FuturesTimeoutError:
                return ValidationFeedback(
                    False,
                    "API validation timed out.",
                    ("Check your internet connection and try again shortly.",),
                )
            except TimeoutError:
                return ValidationFeedback(
                    False,
                    "API validation timed out.",
                    (
                        "The provider took too long to respond.",
                        "Retry in a moment or verify service status.",
                    ),
                )
            except Exception as exc:
                message = str(exc) or "Provider rejected the API key."
                return ValidationFeedback(
                    False,
                    message,
                    (
                        "Confirm the key is still active and has not been revoked.",
                        f"Regenerate the key via {metadata.doc_url} if necessary.",
                    ),
                )

        self.ui.success("✓ Connection successful!")
        return ValidationFeedback(True, "Key validated successfully!")

    def _store_api_key_to_keyring(self, metadata: ProviderMetadata, api_key: str) -> str:
        if not self._keyring_enabled:
            destination = self._write_env_file(metadata, api_key)
            if destination:
                return destination
            os.environ[metadata.env_var] = api_key
            self.ui.warning(
                "Stored key in current session only. You'll need to set it up again next time."
            )
            return "session environment"
        try:
            set_password("french_vocab_builder", metadata.keyring_name, api_key)
            self.ui.success("✓ API key securely saved to system keychain.")
            return "system keyring"
        except Exception as exc:
            self.ui.warning(
                f"Could not access system keychain: {exc}\n"
                "Falling back to .env file storage."
            )
            destination = self._write_env_file(metadata, api_key)
            if destination:
                return destination
            os.environ[metadata.env_var] = api_key
            self.ui.warning(
                "Stored key in current session only. You'll need to set it up again next time."
            )
            return "session environment"

    def _choose_storage_destination(self, metadata: ProviderMetadata, *, keyring_available: bool) -> str:
        options: List[Tuple[str, str]] = []
        if keyring_available:
            options.append(("keyring", "Secure system keyring [dim](recommended)[/dim]"))
        options.append(("env_file", ".env file in project directory"))
        options.append(("session", "Current session only (environment variable)"))
        try:
            choice = self.ui.interactive_menu(
                "Where should we save this key?",
                options,
                "Choose how you want FrenchVocab to remember your key.",
                show_keys=False,
            )
        except KeyboardInterrupt as exc:
            raise RuntimeError("API setup aborted by user.") from exc
        return choice

    def _store_api_key(self, metadata: ProviderMetadata, api_key: str) -> str:
        keyring_available = bool(self._keyring_enabled)
        while True:
            choice = self._choose_storage_destination(metadata, keyring_available=keyring_available)
            if choice == "keyring":
                try:
                    set_password("french_vocab_builder", metadata.keyring_name, api_key)
                    self.ui.success("Saved API key to system keyring.")
                    return "system keyring"
                except Exception:
                    self.ui.warning(
                        "Keyring is not available right now. Choose another storage option."
                    )
                    keyring_available = False
                    continue

            if choice == "env_file":
                destination = self._write_env_file(metadata, api_key)
                if destination:
                    return destination
                continue

            if choice == "session":
                os.environ[metadata.env_var] = api_key
                self.ui.warning(
                    "Stored key in current session only. Run setup again next time if needed."
                )
                return "session environment"

    def _write_env_file(self, metadata: ProviderMetadata, api_key: str) -> Optional[str]:
        env_path = self._env_path
        if env_path.exists() and not env_path.is_file():
            self.ui.error("Cannot write .env file because the path exists and is not a file.")
            return None

        try:
            env_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.ui.error(f"Failed to create config directory {env_path.parent}: {exc}")
            return None

        lines: List[str] = []
        if env_path.exists():
            try:
                lines = env_path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                self.ui.error(f"Failed to read existing .env file: {exc}")
                return None

        updated = False
        new_lines: List[str] = []
        key_var = metadata.env_var
        for line in lines:
            if line.strip().startswith(f"{key_var}="):
                new_lines.append(f"{key_var}={api_key}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"{key_var}={api_key}")

        # Create backup before modification (best-effort)
        if env_path.exists():
            backup_path = env_path.with_suffix(".env.bak")
            try:
                shutil.copy2(env_path, backup_path)
            except OSError as exc:
                self.ui.warning(f"Could not create .env backup: {exc}")
                # Continue anyway - backup is best-effort

        # Use atomic write pattern: write to temp, then rename
        temp_path = env_path.with_suffix(".env.tmp")
        try:
            temp_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            os.replace(temp_path, env_path)
        except OSError as exc:
            self.ui.error(f"Failed to write .env file: {exc}")
            # Clean up temp file if it exists
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            return None

        self.ui.success(f"Saved key to {env_path}.")
        self.ui.info(
            "Future runs will automatically reuse this key from the project .env file."
        )
        return f".env ({env_path})"

    def _display_validation_failure(self, metadata: ProviderMetadata, feedback: ValidationFeedback) -> None:
        details = feedback.message
        if feedback.suggestions:
            suggestions = "\n".join(f"- {tip}" for tip in feedback.suggestions)
            details = f"{details}\n\nSuggestions:\n{suggestions}"

        self.ui.panel(
            details,
            title=f"{metadata.display_name} Validation Failed",
            border_style="#ff6b6b",
            expand=True,
        )


__all__ = [
    "ProviderManager",
    "ProviderMetadata",
    "ProviderResolution",
    "ValidationFeedback",
]
