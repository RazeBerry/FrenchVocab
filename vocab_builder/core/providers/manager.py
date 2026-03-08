import getpass
import os
import tempfile
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency should be present in runtime
    load_dotenv = None  # type: ignore[misc,assignment]

try:
    from keyring.errors import KeyringError
except Exception:  # pragma: no cover - keyring may be absent in some environments
    class KeyringError(Exception):
        """Fallback keyring error when keyring is unavailable."""


from vocab_builder.compat import get_env, config_home, KEYRING_SERVICE
from vocab_builder.llm_client import ProviderFactory
from vocab_builder.ui_helper import UIHelper


def get_password(service: str, name: str) -> Optional[str]:
    """Lazy wrapper around keyring.get_password to avoid importing keyring at startup."""
    import keyring  # type: ignore[import]

    return keyring.get_password(service, name)


def set_password(service: str, name: str, value: str) -> None:
    """Lazy wrapper around keyring.set_password to avoid importing keyring at startup."""
    import keyring  # type: ignore[import]

    keyring.set_password(service, name, value)


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


def available_provider_ids() -> Tuple[str, ...]:
    """Return the supported provider identifiers in a stable order."""
    return tuple(sorted(_PROVIDER_REGISTRY.keys()))


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

    _SILENT_KEYRING_TIMEOUT_S = 1.0
    _PLAINTEXT_SECRET_FILE_MODE = 0o600

    def __init__(self, ui: UIHelper, project_root: Path):
        self.ui = ui
        self.project_root = Path(project_root)
        self._env_path = self._determine_env_path(self.project_root)
        # Allow skipping keyring probing for faster startup in CI/containers.
        skip = get_env("VOCABBUILDER_SKIP_KEYRING", "")
        self._keyring_enabled = str(skip).strip().lower() not in {"1", "true", "yes", "y"}

    # Public API ---------------------------------------------------------
    def get_metadata(self, provider: Optional[str]) -> ProviderMetadata:
        return _get_provider_metadata(provider)

    # Helper: decide where to read/write the .env file
    def _determine_env_path(self, project_root: Path) -> Path:
        """Choose a writable .env location, preferring project root, with fallbacks.

        Order of preference:
        1) VOCABBUILDER_CONFIG_DIR/.env (explicit override)
        2) project_root/.env if writable
        3) ~/.vocabbuilder/.env (falls back to ~/.frenchvocab/ if it exists)
        """

        # 1) Explicit override for tests or custom deployments
        env_dir_override = get_env("VOCABBUILDER_CONFIG_DIR")
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

        # 3) User config dir (with legacy fallback)
        fallback_dir = config_home()
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
        api_key, source = self._resolve_api_key(
            metadata,
            keyring_timeout_s=self._SILENT_KEYRING_TIMEOUT_S,
        )
        if not api_key:
            return None
        return ProviderResolution(metadata=metadata, api_key=api_key, source=source)

    def _keyring_get_password(
        self,
        service: str,
        name: str,
        *,
        timeout_s: Optional[float],
    ) -> Tuple[Optional[str], bool]:
        if timeout_s is None:
            return get_password(service, name), False

        result: Dict[str, Optional[str]] = {"value": None}
        error: Dict[str, Exception] = {}

        def _worker() -> None:
            try:
                result["value"] = get_password(service, name)
            except Exception as exc:  # pragma: no cover - defensive
                error["exc"] = exc

        thread = threading.Thread(
            target=_worker,
            name="vocabbuilder-keyring-get",
            daemon=True,
        )
        thread.start()
        thread.join(timeout_s)

        if thread.is_alive():
            return None, True
        if "exc" in error:
            raise error["exc"]
        return result["value"], False

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
        except OSError as exc:
            self.ui.warning(f"Failed to load {env_path}: {exc}")
            return None

        if loaded:
            self.ui.info(f"Loaded environment variables from {env_path}.")
            return env_path
        return None

    def _resolve_api_key(
        self,
        metadata: ProviderMetadata,
        *,
        keyring_timeout_s: Optional[float] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve an API key from environment first, then keyring as fallback.

        Environment variables (including values loaded from a `.env` file) are treated as
        explicit session overrides. Keyring is used only if the environment does not
        provide a valid key.
        """

        env_value = os.environ.get(metadata.env_var)
        if env_value:
            result = self._validate_api_key(metadata, env_value, perform_connection_test=False)
            if result.valid:
                return env_value, "environment variable"
            self.ui.warning(
                f"Ignoring invalid {metadata.env_var} from environment: {result.message}"
            )

        stored_key = None
        keyring_timed_out = False
        if self._keyring_enabled:
            try:
                stored_key, keyring_timed_out = self._keyring_get_password(
                    KEYRING_SERVICE,
                    metadata.keyring_name,
                    timeout_s=keyring_timeout_s,
                )
            except (KeyringError, RuntimeError, OSError, ValueError, ImportError) as exc:
                self.ui.error(f"Error accessing system keyring: {exc}")

        if keyring_timed_out:
            self.ui.warning(
                "Keychain lookup took too long; skipping it for now. "
                "You can set VOCABBUILDER_SKIP_KEYRING=1 to disable keychain lookups."
            )

        if stored_key:
            result = self._validate_api_key(metadata, stored_key, perform_connection_test=False)
            if result.valid:
                return stored_key, "system keyring"
            self.ui.warning(
                "Stored keychain credential failed validation; ignoring it."
            )

        return None, None

    def _run_setup_wizard(self, default_metadata: ProviderMetadata) -> Tuple[ProviderMetadata, str]:
        self.ui.panel(
            "[bold cyan]🚀 Welcome to VocabBuilder![/bold cyan]\n\n"
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
            persistence_note = "[yellow]You'll be prompted for the key again the next time you launch VocabBuilder.[/yellow]"
            self.ui.warning(
                "Key stored for this session only. Run the setup again next time to restore AI features."
            )

        self.ui.panel(
            "[bold green]✅ All Set![/bold green]\n\n"
            "VocabBuilder is ready to use!\n\n"
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
            set_password(KEYRING_SERVICE, metadata.keyring_name, api_key)
            self.ui.success("✓ API key securely saved to system keychain.")
            return "system keyring"
        except (KeyringError, RuntimeError, OSError, ImportError, ValueError) as exc:
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
                "Choose how you want VocabBuilder to remember your key.",
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
                    set_password(KEYRING_SERVICE, metadata.keyring_name, api_key)
                    self.ui.success("Saved API key to system keyring.")
                    return "system keyring"
                except (KeyringError, RuntimeError, OSError, ImportError, ValueError):
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
        if not self._ensure_env_file_path(env_path):
            return None

        if not self._ensure_parent_dir(env_path):
            return None

        lines = self._read_env_lines(env_path)
        if lines is None:
            return None

        new_lines = self._upsert_env_var(lines, metadata.env_var, api_key)

        if not self._atomic_write_env_lines(env_path, new_lines):
            return None
        self._remove_env_backup_best_effort(env_path)

        self.ui.success(f"Saved key to {env_path}.")
        self.ui.info("Future runs will automatically reuse this key from the project .env file.")
        return f".env ({env_path})"

    def _ensure_env_file_path(self, env_path: Path) -> bool:
        if env_path.exists() and not env_path.is_file():
            self.ui.error("Cannot write .env file because the path exists and is not a file.")
            return False
        return True

    def _ensure_parent_dir(self, env_path: Path) -> bool:
        try:
            env_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.ui.error(f"Failed to create config directory {env_path.parent}: {exc}")
            return False
        return True

    def _read_env_lines(self, env_path: Path) -> Optional[List[str]]:
        if not env_path.exists():
            return []
        try:
            return env_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            self.ui.error(f"Failed to read existing .env file: {exc}")
            return None

    @staticmethod
    def _upsert_env_var(lines: List[str], key_var: str, api_key: str) -> List[str]:
        new_lines: List[str] = []
        updated = False
        prefix = f"{key_var}="
        for line in lines:
            if line.strip().startswith(prefix):
                new_lines.append(f"{key_var}={api_key}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"{key_var}={api_key}")
        return new_lines

    @staticmethod
    def _legacy_backup_paths(env_path: Path) -> Tuple[Path, ...]:
        candidates = [env_path.parent / f"{env_path.name}.bak"]
        legacy_suffix_path = env_path.with_suffix(".env.bak")
        if legacy_suffix_path not in candidates:
            candidates.append(legacy_suffix_path)
        return tuple(candidates)

    def _remove_env_backup_best_effort(self, env_path: Path) -> None:
        for backup_path in self._legacy_backup_paths(env_path):
            if not backup_path.exists():
                continue
            try:
                backup_path.unlink()
            except OSError as exc:
                self.ui.warning(f"Could not remove stale .env backup {backup_path}: {exc}")

    def _restrict_env_file_permissions_best_effort(self, path: Path) -> None:
        if os.name == "nt":
            return
        try:
            os.chmod(path, self._PLAINTEXT_SECRET_FILE_MODE)
        except OSError as exc:
            self.ui.warning(f"Could not tighten permissions on {path}: {exc}")

    def _atomic_write_env_lines(self, env_path: Path, lines: List[str]) -> bool:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{env_path.name}.",
            suffix=".tmp",
            dir=env_path.parent,
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            if hasattr(os, "fchmod") and os.name != "nt":
                os.fchmod(fd, self._PLAINTEXT_SECRET_FILE_MODE)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, env_path)
            self._restrict_env_file_permissions_best_effort(env_path)
            return True
        except OSError as exc:
            self.ui.error(f"Failed to write .env file: {exc}")
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        return False

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
    "available_provider_ids",
]
