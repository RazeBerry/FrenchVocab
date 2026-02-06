"""LLM provider lifecycle management and query coordination.

This module handles:
- Provider initialization and credential management
- Background LLM initialization
- Degraded mode (offline) handling
- AI query streaming with metrics
- Session token usage tracking
"""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from rich.progress import Progress


class InitState(Enum):
    """State machine for LLM initialization lifecycle."""
    NOT_STARTED = auto()    # No initialization attempted yet
    IN_PROGRESS = auto()    # Background thread is running
    READY = auto()          # Client initialized successfully
    FAILED = auto()         # Initialization failed (credentials, network, etc.)
    DEFERRED = auto()       # No credentials found, waiting for user setup


@contextmanager
def _suppress_stdin_echo():
    """Suppress stdin echo during progress spinners to prevent Enter key artifacts."""
    if not sys.stdin.isatty():
        yield
        return

    if sys.platform.startswith("win"):
        # Windows: no simple echo suppression; just yield
        yield
        return

    try:
        import termios
        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)
        new_attrs = old_attrs[:]
        new_attrs[3] = new_attrs[3] & ~termios.ECHO  # Disable echo
        termios.tcsetattr(fd, termios.TCSANOW, new_attrs)
        try:
            yield
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
            # Flush any buffered input that accumulated during the query
            termios.tcflush(fd, termios.TCIFLUSH)
    except Exception:
        yield

if TYPE_CHECKING:
    from llm_client import LLMClient
    from ui_helper import UIHelper
    from core.providers.manager import ProviderManager, ProviderMetadata, ProviderResolution


class LLMCoordinator:
    """Manages LLM provider lifecycle, queries, and usage tracking.

    This class extracts LLM-related concerns from FrenchVocabBuilder to provide
    a focused, testable component for AI provider management.
    """

    def __init__(
        self,
        ui: "UIHelper",
        provider_manager: "ProviderManager" | None = None,
        provider_metadata: "ProviderMetadata" | None = None,
        verbose: bool = False,
        client: Optional["LLMClient"] = None,
        eager: bool = False,
        project_root: Optional[Path] = None,
    ):
        """Initialize the LLM coordinator.

        Args:
            ui: UIHelper instance for user interaction
            provider_manager: ProviderManager for credential handling
            provider_metadata: Metadata for the selected provider
            verbose: Enable verbose output
            client: Optional pre-configured LLM client (for testing/injection)
            eager: If True, initialize client immediately; otherwise defer
        """
        self._ui = ui
        if provider_manager is None:
            from core.providers.manager import ProviderManager as _ProviderManager

            root = Path(project_root) if project_root is not None else Path.cwd()
            provider_manager = _ProviderManager(ui, root)

        self._provider_manager = provider_manager
        self._provider_metadata = provider_metadata or self._provider_manager.get_metadata(None)
        self._verbose = verbose

        # Client state (protected by _state_lock for thread safety)
        self._state_lock = threading.Lock()
        self._client: Optional["LLMClient"] = client
        self._api_error_reason: Optional[str] = None

        # Initialization state machine (single source of truth)
        self._init_state: InitState = InitState.READY if client else InitState.NOT_STARTED
        self._init_event = threading.Event()  # Signals when init completes (success or failure)
        if client:
            self._init_event.set()  # Already initialized

        # Background initialization state (legacy, kept for property compatibility)
        self._llm_thread: Optional[threading.Thread] = None
        self._llm_init_error: Optional[Exception] = None

        # Session usage tracking
        self._session_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "thoughts_tokens": 0,
            "tool_tokens": 0,
            "cached_tokens": 0,
        }
        self._session_requests: int = 0

        # Callback for degraded mode (set by owner)
        self._on_degraded_mode: Optional[Callable[[str], None]] = None
        # Callback for successful initialization (set by owner)
        self._on_client_ready: Optional[Callable[[], None]] = None

        # Initialize based on mode
        if client is None:
            if eager:
                if self._prepare_provider():
                    self._initialize_client()
                else:
                    self._enter_degraded_mode(self.api_error_reason or "API setup skipped.")
            else:
                self._start_background_init()
        else:
            pass  # client already set, state already READY from __init__

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def client(self) -> Optional["LLMClient"]:
        """The active LLM client, or None if unavailable."""
        with self._state_lock:
            return self._client

    @client.setter
    def client(self, value: Optional["LLMClient"]) -> None:
        """Set the LLM client directly."""
        with self._state_lock:
            self._client = value
            if value is not None:
                self._init_state = InitState.READY
                self._api_error_reason = None
                self._init_event.set()
            else:
                self._init_state = InitState.FAILED

    @property
    def init_state(self) -> InitState:
        """Current initialization state (single source of truth)."""
        with self._state_lock:
            return self._init_state

    @property
    def api_available(self) -> bool:
        """Whether the AI provider is available for queries."""
        return self.init_state == InitState.READY

    @api_available.setter
    def api_available(self, value: bool) -> None:
        """Set API availability directly (for backward compatibility)."""
        with self._state_lock:
            self._init_state = InitState.READY if value else InitState.FAILED

    @property
    def api_error_reason(self) -> Optional[str]:
        """Reason for API unavailability, if any."""
        with self._state_lock:
            return self._api_error_reason

    @api_error_reason.setter
    def api_error_reason(self, value: Optional[str]) -> None:
        """Set the API error reason."""
        with self._state_lock:
            self._api_error_reason = value

    @property
    def provider(self) -> str:
        """The active provider identifier."""
        return self._provider_metadata.identifier

    @property
    def provider_metadata(self) -> "ProviderMetadata":
        """Full metadata for the active provider."""
        return self._provider_metadata

    @provider_metadata.setter
    def provider_metadata(self, value: "ProviderMetadata") -> None:
        """Update the provider metadata."""
        self._provider_metadata = value

    @property
    def provider_label(self) -> str:
        """Human-readable label for the active provider/model."""
        label = self._provider_metadata.identifier.capitalize()
        if self._client is not None:
            getter = getattr(self._client, "model_label", None)
            if callable(getter):
                try:
                    label = getter()
                except Exception:
                    label = self._client.__class__.__name__
        return label

    @property
    def session_usage(self) -> Dict[str, int]:
        """Session token usage statistics."""
        return self._session_usage

    @property
    def session_requests(self) -> int:
        """Number of AI requests in this session."""
        return self._session_requests

    @property
    def llm_thread(self) -> Optional[threading.Thread]:
        """The background initialization thread, if any."""
        return self._llm_thread

    # -------------------------------------------------------------------------
    # Provider Resolution
    # -------------------------------------------------------------------------

    def _apply_provider_resolution(self, resolution: "ProviderResolution") -> None:
        """Persist provider metadata and API key details after successful setup."""
        self._provider_metadata = resolution.metadata
        os.environ[resolution.metadata.env_var] = resolution.api_key
        with self._state_lock:
            self._api_error_reason = None

    def _prepare_provider(self) -> bool:
        """Ensure provider credentials are ready; return False when setup is skipped."""
        try:
            resolution = self._provider_manager.prepare_provider(self._provider_metadata)
        except RuntimeError as exc:
            message = str(exc) or "API setup aborted by user."
            with self._state_lock:
                self._api_error_reason = message
            self._ui.error(message, with_panel=True)
            return False

        self._apply_provider_resolution(resolution)
        return True

    # -------------------------------------------------------------------------
    # Client Initialization
    # -------------------------------------------------------------------------

    def _initialize_client(
        self,
        *,
        announce: bool = True,
        on_success: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Create the LLM client for the active provider.

        Args:
            announce: Show success message to user
            on_success: Callback invoked after successful initialization

        Returns:
            True if client was successfully created
        """
        from llm_client import ProviderFactory

        try:
            new_client = ProviderFactory.create(self._provider_metadata.identifier)
        except Exception as exc:
            self._enter_degraded_mode(f"Error initializing {self._provider_metadata.identifier} client: {exc}")
            return False

        with self._state_lock:
            self._client = new_client
            self._init_state = InitState.READY
            self._api_error_reason = None
            self._init_event.set()
        if announce:
            self._ui.success(f"{self._provider_metadata.identifier.capitalize()} client initialized successfully!")
        if on_success:
            on_success()
        # Also invoke the persistent client-ready callback if registered
        if self._on_client_ready:
            self._on_client_ready()
        return True

    def _start_background_init(self) -> None:
        """Kick off non-blocking LLM setup without blocking startup on keyring/env lookups."""
        with self._state_lock:
            if self._init_state != InitState.NOT_STARTED:
                return  # Already started or completed
            self._init_state = InitState.IN_PROGRESS
            self._api_error_reason = "LLM initialization in background."

        def _worker():
            try:
                resolution = self._provider_manager.resolve_provider_silently(self._provider_metadata)
                if not resolution:
                    # No credentials; switch to deferred state
                    with self._state_lock:
                        self._init_state = InitState.DEFERRED
                        self._api_error_reason = "No credentials found. Configure provider on first AI use."
                    return

                self._apply_provider_resolution(resolution)
                # _initialize_client sets state to READY on success
                self._initialize_client(announce=False)
            except Exception as exc:  # pragma: no cover - defensive
                self._llm_init_error = exc
                with self._state_lock:
                    self._init_state = InitState.FAILED
                    self._api_error_reason = str(exc)
            finally:
                # Signal completion regardless of outcome
                self._init_event.set()
                self._llm_thread = None

        self._llm_init_error = None
        self._llm_thread = threading.Thread(target=_worker, name="llm-init", daemon=True)
        self._llm_thread.start()

    def await_init(self, timeout: Optional[float] = None) -> bool:
        """Wait for initialization to complete.

        Args:
            timeout: Maximum seconds to wait. None = wait forever.

        Returns:
            True if client is ready for queries.
        """
        self._init_event.wait(timeout=timeout)
        return self.init_state == InitState.READY

    def await_background_init(self, timeout: float = 5.0) -> bool:
        """Wait for background init to finish; return True if client available.

        DEPRECATED: Use await_init() instead for cleaner semantics.
        """
        return self.await_init(timeout=timeout)

    # -------------------------------------------------------------------------
    # Degraded Mode
    # -------------------------------------------------------------------------

    def _enter_degraded_mode(self, reason: str) -> None:
        """Disable AI-dependent features while keeping the rest of the app usable."""
        clean_reason = (reason or "").strip() or "No AI provider configured."
        with self._state_lock:
            self._client = None
            self._init_state = InitState.FAILED
            self._api_error_reason = clean_reason
            self._init_event.set()  # Signal that init attempt is complete
        self._ui.warning(f"AI features unavailable: {clean_reason}")
        self._ui.info(
            "Existing vocabulary and exports remain accessible. Retry provider setup when prompted to restore AI features."
        )
        # Notify owner to clear dependent state (e.g., translators)
        if self._on_degraded_mode:
            self._on_degraded_mode(clean_reason)

    def set_degraded_mode_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """Register a callback to invoke when entering degraded mode.

        The callback receives the reason string and should clear dependent state
        (e.g., translator instances).
        """
        self._on_degraded_mode = callback

    def set_client_ready_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Register a callback to invoke when the LLM client becomes available.

        This is called after successful background initialization to allow
        dependent components (e.g., translators) to be initialized.
        """
        self._on_client_ready = callback

    # -------------------------------------------------------------------------
    # Readiness & Reconfiguration
    # -------------------------------------------------------------------------

    def ensure_ready(
        self,
        on_settings: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Ensure the LLM client is available, prompting for reconfiguration if needed.

        Args:
            on_settings: Callback to open settings screen when user chooses that option

        Returns:
            True if client is ready for queries
        """
        while True:
            state = self.init_state

            # Already ready - fast path
            if state == InitState.READY:
                return True

            # Background init in progress - wait for it to complete (no arbitrary timeout!)
            if state == InitState.IN_PROGRESS:
                self._init_event.wait()  # Block until init signals completion
                if self.init_state == InitState.READY:
                    return True

            # If we get here, init failed or was deferred - need user action
            if self.client:
                return True

            reason = self.api_error_reason or "No AI provider configured."
            self._ui.warning(f"AI provider unavailable: {reason}")

            options = [
                ("retry", "Retry provider setup now"),
                ("settings", "Open AI settings"),
                ("skip", "Return without AI features"),
            ]

            try:
                choice = self._ui.interactive_menu(
                    "AI Provider Required",
                    options,
                    "AI-powered features need a configured provider • [Esc] Skip",
                    show_keys=False,
                )
            except KeyboardInterrupt:
                return False

            if choice == "retry":
                if self.reconfigure():
                    return True
                self._ui.warning("Provider setup failed. Remaining in offline mode.")
            elif choice == "settings":
                if on_settings:
                    on_settings()
                continue  # Loop back to re-check readiness
            else:
                return False

    def reconfigure(self, on_success: Optional[Callable[[], None]] = None) -> bool:
        """Run provider setup again and rebuild dependent components.

        Args:
            on_success: Callback invoked after successful reconfiguration

        Returns:
            True if reconfiguration was successful
        """
        self._ui.info("Re-running provider setup...")
        if not self._prepare_provider():
            return False
        return self._initialize_client(on_success=on_success)

    # -------------------------------------------------------------------------
    # Provider Switching
    # -------------------------------------------------------------------------

    def change_provider_interactive(
        self,
        on_success: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Allow user to switch between providers.

        Args:
            on_success: Callback invoked after successful switch

        Returns:
            True if provider was changed successfully
        """
        current = self._provider_metadata

        try:
            resolution = self._provider_manager.change_provider(current)
        except RuntimeError as exc:
            self._ui.error(str(exc) or "API setup aborted by user.")
            return False

        if not resolution:
            return False

        self._apply_provider_resolution(resolution)
        return self._initialize_client(announce=True, on_success=on_success)

    def update_api_key_interactive(
        self,
        on_success: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Allow user to update their API key for the current provider.

        Args:
            on_success: Callback invoked after successful key update

        Returns:
            True if key was updated successfully
        """
        if not self._provider_metadata:
            self._ui.error("No provider configured.")
            return False

        resolution = self._provider_manager.update_key(self._provider_metadata)
        if not resolution:
            return False

        self._apply_provider_resolution(resolution)
        return self._initialize_client(announce=True, on_success=on_success)

    # -------------------------------------------------------------------------
    # AI Query
    # -------------------------------------------------------------------------

    def query(
        self,
        prompt: str,
        progress_label: Optional[str] = None,
        on_exception: Optional[Callable[["Exception", str], bool]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Execute an AI query with streaming progress.

        Args:
            prompt: The prompt to send to the AI
            progress_label: Label for the progress indicator (defaults to provider label)
            on_exception: Optional handler for exceptions during streaming.
                          Receives (exception, provider_label) and returns True if handled.

        Returns:
            Tuple of (response_text, metrics_dict)
        """
        label = progress_label or self.provider_label

        if not self.client:
            reason = self.api_error_reason or f"{label} client is not configured."
            self._ui.error(f"Cannot query AI provider: {reason}")
            self._ui.info("AI-powered suggestions are disabled. Retry provider setup to continue.")
            return "", {}

        metrics: Dict[str, Any] = {}
        full_text = ""

        # Suppress stdin echo to prevent Enter keypresses from creating
        # duplicate spinner lines during the query
        with _suppress_stdin_echo(), Progress() as progress:
            task = progress.add_task(f"[cyan]Querying {label}...", total=None)

            chunks: List[str] = []
            generator = self.client.stream(prompt)

            try:
                while True:
                    try:
                        text = next(generator)
                        chunks.append(text)
                        progress.advance(task)
                    except StopIteration as e:
                        # Generator is exhausted, capture the return value (metrics)
                        metrics = e.value if e.value else {}
                        break
            except Exception as e:
                # Handle potential errors during streaming
                handled = False
                if on_exception:
                    handled = on_exception(e, label)
                if not handled:
                    self._ui.error(f"Error during {label} stream: {e}")
                # Ensure generator cleanup runs
                generator.close()
                # Set default metrics if none were captured
                if not metrics:
                    metrics = {'ttft': -1, 'tps': -1, 'tokens_out': -1}
                self._ui.display_metrics(metrics)
                return "", metrics
            finally:
                progress.update(task, completed=True)

            full_text = "".join(chunks)

        self._ui.display_metrics(metrics)
        self.record_usage(metrics.get("usage"))

        return full_text, metrics

    # -------------------------------------------------------------------------
    # Exception Handling
    # -------------------------------------------------------------------------

    def handle_ai_exception(
        self,
        exc: Exception,
        provider_label: str,
        on_settings: Optional[Callable[[], None]] = None,
        on_switch_success: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Handle common AI provider failures and offer recovery paths.

        Args:
            exc: The exception that occurred
            provider_label: Label for the provider that failed
            on_settings: Callback to open settings screen
            on_switch_success: Callback invoked after successful provider switch

        Returns:
            True if the error was handled and no further generic message should be shown
        """
        message = str(exc) or exc.__class__.__name__
        lower = message.lower()

        region_blocked = ("location is not supported" in lower) or (
            "failed_precondition" in lower and "location" in lower
        )

        if region_blocked:
            self._enter_degraded_mode("Gemini is blocked in this region (FAILED_PRECONDITION).")
            self._ui.error(
                "Google Gemini rejected the request because your current region is not supported.\n"
                "Switch to another provider (Anthropic Claude is recommended) or retry from a supported location.",
                with_panel=True,
            )

            options = [
                ("switch", "Switch provider (Claude recommended)"),
                ("settings", "Open AI settings"),
                ("skip", "Return to main menu"),
            ]

            try:
                choice = self._ui.interactive_menu(
                    "Gemini is region-locked here. How should we proceed?",
                    options,
                    "Choose 'switch' to continue without Gemini.",
                )
            except KeyboardInterrupt:
                return True

            if choice == "switch":
                self.change_provider_interactive(on_success=on_switch_success)
            elif choice == "settings":
                if on_settings:
                    on_settings()

            return True

        return False

    # -------------------------------------------------------------------------
    # Usage Tracking
    # -------------------------------------------------------------------------

    def record_usage(self, usage: Optional[Dict[str, int]]) -> None:
        """Aggregate per-session token usage for the exit summary."""
        if not usage:
            return
        self._session_requests += 1
        for key, value in usage.items():
            if value is None:
                continue
            self._session_usage[key] = self._session_usage.get(key, 0) + int(value)

    def format_token_summary(self) -> str:
        """Format session token usage for display."""
        tokens = {k: v for k, v in self._session_usage.items() if v}
        if not tokens:
            return ""

        labels = [
            ("prompt_tokens", "Input"),
            ("output_tokens", "Output"),
            ("total_tokens", "Total"),
            ("thoughts_tokens", "Thoughts"),
            ("tool_tokens", "Tool Prompts"),
            ("cached_tokens", "Cache"),
        ]
        parts: List[str] = []
        for key, label in labels:
            value = tokens.pop(key, None)
            if value is not None:
                parts.append(f"{label}: {value:,}")
        for key, value in tokens.items():
            friendly = key.replace("_", " ").title()
            parts.append(f"{friendly}: {value:,}")

        prefix = f"Sessions: {self._session_requests} | " if self._session_requests else ""
        return prefix + " | ".join(parts)

    # -------------------------------------------------------------------------
    # Verbose Output
    # -------------------------------------------------------------------------

    @property
    def verbose(self) -> bool:
        """Whether verbose output is enabled."""
        return self._verbose

    @verbose.setter
    def verbose(self, value: bool) -> None:
        """Set verbose mode."""
        self._verbose = value
