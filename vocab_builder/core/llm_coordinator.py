"""LLM provider lifecycle management and query coordination.

This module handles:
- Provider initialization and credential management
- Background LLM initialization
- Degraded mode (offline) handling
- AI query streaming with metrics
- Session token usage tracking
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from rich.progress import Progress

from vocab_builder.compat import get_env


_PROVIDER_RETRY_COOLDOWN_S = 30.0


def _provider_retry_cooldown() -> float:
    """Return the minimum delay between silent provider recovery attempts."""
    raw = get_env("VOCABBUILDER_PROVIDER_RETRY_COOLDOWN")
    if raw is None:
        return _PROVIDER_RETRY_COOLDOWN_S
    try:
        value = float(raw.strip())
    except (AttributeError, TypeError, ValueError):
        return _PROVIDER_RETRY_COOLDOWN_S
    if not math.isfinite(value) or value < 0:
        return _PROVIDER_RETRY_COOLDOWN_S
    return value


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
    except (OSError, ValueError, AttributeError):
        yield

if TYPE_CHECKING:
    from vocab_builder.llm_client import LLMClient
    from vocab_builder.ui_helper import UIHelper
    from vocab_builder.core.providers.manager import ProviderManager, ProviderMetadata, ProviderResolution


class LLMCoordinator:
    """Manages LLM provider lifecycle, queries, and usage tracking.

    This class extracts LLM-related concerns from VocabBuilder to provide
    a focused, testable component for AI provider management.
    """

    _BACKGROUND_INIT_WAIT_TIMEOUT_S = 5.0
    _CREDENTIAL_VERIFY_TIMEOUT_S = 5.0

    def __init__(
        self,
        ui: "UIHelper",
        provider_manager: "ProviderManager" | None = None,
        provider_metadata: "ProviderMetadata" | None = None,
        verbose: bool = False,
        client: Optional["LLMClient"] = None,
        eager: bool = False,
        project_root: Optional[Path] = None,
        *,
        interactive: bool = True,
    ):
        """Initialize the LLM coordinator.

        Args:
            ui: UIHelper instance for user interaction
            provider_manager: ProviderManager for credential handling
            provider_metadata: Metadata for the selected provider
            verbose: Enable verbose output
            client: Optional pre-configured LLM client (for testing/injection)
            eager: If True, initialize client immediately; otherwise defer
            interactive: Whether console prompts and progress rendering are allowed
        """
        self._ui = ui
        if provider_manager is None:
            from vocab_builder.compat import runtime_root
            from vocab_builder.core.providers.manager import ProviderManager as _ProviderManager

            if project_root is not None:
                root = Path(project_root)
            else:
                source_root = Path(__file__).resolve().parent.parent.parent
                root = runtime_root(source_root, create=True)
            provider_manager = _ProviderManager(ui, root)

        self._provider_manager = provider_manager
        self._provider_metadata = provider_metadata or self._provider_manager.get_metadata(None)
        self._verbose = verbose
        self._interactive = interactive

        # Client state (protected by _state_lock for thread safety)
        self._state_lock = threading.Lock()
        # Provider clients are stateful and are not required to support two
        # simultaneous streams. Keep lifecycle state independently readable,
        # but serialize queries for one coordinator. Separate language builders
        # still query in parallel because each owns its own coordinator.
        self._query_lock = threading.Lock()
        self._usage_lock = threading.Lock()
        self._client: Optional["LLMClient"] = client
        self._api_error_reason: Optional[str] = None
        self._last_query_error_reason: Optional[str] = None
        self._init_generation: int = 0
        self._last_silent_reinit_attempt: Optional[float] = None
        self._silent_reinit_in_progress = False

        # Initialization state machine (single source of truth)
        self._init_state: InitState = InitState.READY if client else InitState.NOT_STARTED
        self._init_event = threading.Event()  # Signals when init completes (success or failure)
        if client:
            self._init_event.set()  # Already initialized

        # Background initialization state
        self._llm_thread: Optional[threading.Thread] = None

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
                self._init_event.set()

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
    def last_query_error_reason(self) -> Optional[str]:
        """Return the most recent request-scoped provider error, if any."""
        with self._state_lock:
            return self._last_query_error_reason

    def _set_last_query_error(self, reason: Optional[str]) -> None:
        with self._state_lock:
            self._last_query_error_reason = reason

    def clear_last_query_error(self) -> None:
        """Clear request-scoped provider feedback before a direct client query."""
        self._set_last_query_error(None)

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
                except (RuntimeError, ValueError, TypeError, AttributeError):
                    label = self._client.__class__.__name__
        return label

    @property
    def provider_model(self) -> str:
        """Bare model identifier for the active provider, or an empty string."""
        if self._client is None:
            return ""
        getter = getattr(self._client, "model_name", None)
        if not callable(getter):
            return ""
        try:
            return getter()
        except (RuntimeError, ValueError, TypeError, AttributeError):
            return ""

    @property
    def session_usage(self) -> Dict[str, int]:
        """Session token usage statistics."""
        with self._usage_lock:
            return dict(self._session_usage)

    @property
    def session_requests(self) -> int:
        """Number of AI requests in this session."""
        with self._usage_lock:
            return self._session_requests

    @property
    def llm_thread(self) -> Optional[threading.Thread]:
        """The background initialization thread, if any."""
        return self._llm_thread

    # -------------------------------------------------------------------------
    # Provider Resolution
    # -------------------------------------------------------------------------

    def _apply_provider_resolution(
        self,
        resolution: "ProviderResolution",
        *,
        generation: Optional[int] = None,
    ) -> bool:
        """Persist provider metadata and API key details after successful setup."""
        with self._state_lock:
            if generation is not None and generation != getattr(self, "_init_generation", 0):
                return False
            os.environ[resolution.metadata.env_var] = resolution.api_key
            self._provider_metadata = resolution.metadata
            self._api_error_reason = None
            return True

    def _start_init_attempt(self, reason: str) -> int:
        with self._state_lock:
            self._init_generation = getattr(self, "_init_generation", 0) + 1
            generation = self._init_generation
            self._init_state = InitState.IN_PROGRESS
            self._api_error_reason = reason
            self._init_event.clear()
            return generation

    def _generation_is_current(self, generation: int) -> bool:
        with self._state_lock:
            return generation == getattr(self, "_init_generation", 0)

    def _invalidate_background_init(self, reason: str) -> bool:
        with self._state_lock:
            if self._init_state != InitState.IN_PROGRESS:
                return False
            self._init_generation = getattr(self, "_init_generation", 0) + 1
            self._init_state = InitState.FAILED
            self._api_error_reason = reason
            self._init_event.set()
            return True

    def _mark_generation_unavailable(
        self,
        generation: int,
        *,
        state: InitState,
        reason: str,
    ) -> bool:
        with self._state_lock:
            if generation != getattr(self, "_init_generation", 0):
                return False
            self._client = None
            self._init_state = state
            self._api_error_reason = reason
            self._init_event.set()
            return True

    @staticmethod
    def _classify_provider_error(provider_name: str, exc: Exception) -> Optional[Tuple[str, str]]:
        try:
            from vocab_builder.llm_client import classify_provider_error  # type: ignore[attr-defined]
        except (ImportError, AttributeError):
            return None
        return classify_provider_error(provider_name, exc)

    def _prepare_provider(self, *, generation: Optional[int] = None) -> bool:
        """Ensure provider credentials are ready; return False when setup is skipped."""
        try:
            resolution = self._provider_manager.prepare_provider(self._provider_metadata)
        except RuntimeError as exc:
            message = str(exc) or "API setup aborted by user."
            with self._state_lock:
                self._api_error_reason = message
            self._ui.error(message, with_panel=True)
            return False

        return self._apply_provider_resolution(resolution, generation=generation)

    # -------------------------------------------------------------------------
    # Client Initialization
    # -------------------------------------------------------------------------

    def _initialize_client(
        self,
        *,
        announce: bool = True,
        on_success: Optional[Callable[[], None]] = None,
        generation: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> bool:
        """Create the LLM client for the active provider.

        Args:
            announce: Show success message to user
            on_success: Callback invoked after successful initialization
            api_key: Resolved credential to pass directly to the provider factory

        Returns:
            True if client was successfully created
        """
        from vocab_builder.llm_client import ProviderFactory

        metadata = self._provider_metadata
        try:
            if api_key is None:
                new_client = ProviderFactory.create(metadata.identifier)
            else:
                new_client = ProviderFactory.create(metadata.identifier, api_key)
            verifier = getattr(new_client, "verify_credentials", None)
            if callable(verifier):
                verifier(timeout=self._CREDENTIAL_VERIFY_TIMEOUT_S)
        except Exception as exc:
            classified = self._classify_provider_error(metadata.identifier, exc)
            message = (
                classified[1]
                if classified is not None
                else f"Error initializing {metadata.identifier} client: {exc}"
            )
            self._enter_degraded_mode(message, generation=generation)
            return False

        with self._state_lock:
            if generation is not None and generation != self._init_generation:
                return False
            self._client = new_client
            self._init_state = InitState.READY
            self._api_error_reason = None
            self._init_event.set()
        if announce:
            self._ui.success(f"{metadata.identifier.capitalize()} client initialized successfully!")
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
        generation = self._start_init_attempt("LLM initialization in background.")
        metadata = self._provider_metadata

        def _worker():
            try:
                resolution = self._provider_manager.resolve_provider_silently(metadata)
                if not resolution:
                    self._mark_generation_unavailable(
                        generation,
                        state=InitState.DEFERRED,
                        reason="No credentials found. Configure provider on first AI use.",
                    )
                    return

                if not self._generation_is_current(generation):
                    return
                if not self._apply_provider_resolution(resolution, generation=generation):
                    return
                # _initialize_client sets state to READY on success
                self._initialize_client(announce=False, generation=generation)
            except Exception as exc:  # pragma: no cover - defensive
                self._mark_generation_unavailable(
                    generation,
                    state=InitState.FAILED,
                    reason=str(exc) or "Background provider initialization failed.",
                )
            finally:
                with self._state_lock:
                    if self._llm_thread is threading.current_thread():
                        self._llm_thread = None

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

    # -------------------------------------------------------------------------
    # Degraded Mode
    # -------------------------------------------------------------------------

    def _enter_degraded_mode(self, reason: str, *, generation: Optional[int] = None) -> bool:
        """Disable AI-dependent features while keeping the rest of the app usable."""
        clean_reason = (reason or "").strip() or "No AI provider configured."
        with self._state_lock:
            if generation is not None and generation != self._init_generation:
                return False
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
        return True

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

    def try_silent_reinit(self) -> bool:
        """Attempt bounded, non-interactive recovery of a degraded provider."""
        with self._state_lock:
            if self._init_state == InitState.READY:
                return True

        now = time.monotonic()
        cooldown = _provider_retry_cooldown()
        with self._state_lock:
            # The provider may have recovered while configuration was read.
            if self._init_state == InitState.READY:
                return True
            if getattr(self, "_silent_reinit_in_progress", False):
                return False

            last_attempt = getattr(self, "_last_silent_reinit_attempt", None)
            if last_attempt is not None and now - last_attempt < cooldown:
                return False

            self._last_silent_reinit_attempt = now
            self._silent_reinit_in_progress = True
            self._init_generation = getattr(self, "_init_generation", 0) + 1
            generation = self._init_generation
            metadata = self._provider_metadata

        try:
            resolution = self._provider_manager.resolve_provider_silently(metadata)
            if resolution is None:
                return False
            if not self._apply_provider_resolution(
                resolution,
                generation=generation,
            ):
                return False
            return self._initialize_client(
                announce=False,
                generation=generation,
                api_key=resolution.api_key,
            )
        finally:
            with self._state_lock:
                self._silent_reinit_in_progress = False

    def apply_resolution_noninteractive(self, resolution: "ProviderResolution") -> bool:
        """Switch to a validated provider resolution without console prompts."""
        self._invalidate_background_init(
            "Non-interactive provider configuration superseded background initialization."
        )
        generation = self._start_init_attempt("Applying provider configuration.")
        if not self._apply_provider_resolution(resolution, generation=generation):
            return False
        return self._initialize_client(
            announce=False,
            generation=generation,
            api_key=resolution.api_key,
        )

    def test_connection(self) -> tuple[bool, str]:
        """Verify the current provider without exposing its credential."""
        with self._query_lock:
            client = self.client
            if client is None:
                return False, self.api_error_reason or "The AI provider is unavailable."
            verifier = getattr(client, "verify_credentials", None)
            if not callable(verifier):
                return True, f"{self.provider_label} is ready."
            try:
                verifier(timeout=self._CREDENTIAL_VERIFY_TIMEOUT_S)
            except Exception as exc:
                classified = self._classify_provider_error(self.provider, exc)
                reason = classified[1] if classified is not None else str(exc)
                self._enter_degraded_mode(reason)
                return False, reason
            return True, f"{self.provider_label} is connected."

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
            if self.init_state == InitState.READY:
                return True

            if self._wait_for_background_init_if_needed():
                return True

            # If we get here, init failed or was deferred - need user action
            if self.client:
                return True

            choice = self._prompt_readiness_action()
            outcome = self._apply_readiness_action(choice, on_settings=on_settings)
            if outcome is not None:
                return outcome

    def _wait_for_background_init_if_needed(self) -> bool:
        """Wait for background init to complete when needed.

        Returns:
            True if initialization completed successfully and the client is ready.
        """
        if self.init_state != InitState.IN_PROGRESS:
            return False

        completed = self._init_event.wait(timeout=self._BACKGROUND_INIT_WAIT_TIMEOUT_S)
        if not completed and self.init_state == InitState.IN_PROGRESS:
            self._invalidate_background_init(
                "Background provider initialization timed out. Retry setup to continue."
            )
            return False
        return self.init_state == InitState.READY

    def _prompt_readiness_action(self) -> str:
        reason = self.api_error_reason or "No AI provider configured."
        self._ui.warning(f"AI provider unavailable: {reason}")

        options = [
            ("retry", "Retry provider setup now"),
            ("settings", "Open AI settings"),
            ("skip", "Return without AI features"),
        ]

        try:
            return self._ui.interactive_menu(
                "AI Provider Required",
                options,
                "AI-powered features need a configured provider • [Esc] Skip",
                show_keys=False,
            )
        except KeyboardInterrupt:
            return "skip"

    def _apply_readiness_action(
        self,
        choice: str,
        *,
        on_settings: Optional[Callable[[], None]],
    ) -> Optional[bool]:
        """Return True/False to stop, or None to continue loop."""
        if choice == "retry":
            if self.reconfigure():
                return True
            self._ui.warning("Provider setup failed. Remaining in offline mode.")
            return None
        if choice == "settings":
            if on_settings:
                on_settings()
            return None
        return False

    def reconfigure(self, on_success: Optional[Callable[[], None]] = None) -> bool:
        """Run provider setup again and rebuild dependent components.

        Args:
            on_success: Callback invoked after successful reconfiguration

        Returns:
            True if reconfiguration was successful
        """
        self._invalidate_background_init("Provider setup was interrupted by manual reconfiguration.")
        self._ui.info("Re-running provider setup...")
        generation = self._start_init_attempt("Re-running provider setup.")
        if not self._prepare_provider(generation=generation):
            self._mark_generation_unavailable(
                generation,
                state=InitState.FAILED,
                reason=self.api_error_reason or "Provider setup failed.",
            )
            return False
        return self._initialize_client(on_success=on_success, generation=generation)

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
        self._invalidate_background_init("Provider change superseded background initialization.")
        current = self._provider_metadata

        try:
            resolution = self._provider_manager.change_provider(current)
        except RuntimeError as exc:
            self._ui.error(str(exc) or "API setup aborted by user.")
            return False

        if not resolution:
            return False

        generation = self._start_init_attempt("Changing AI provider.")
        if not self._apply_provider_resolution(resolution, generation=generation):
            return False
        return self._initialize_client(
            announce=True,
            on_success=on_success,
            generation=generation,
        )

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
        self._invalidate_background_init("API key update superseded background initialization.")
        if not self._provider_metadata:
            self._ui.error("No provider configured.")
            return False

        resolution = self._provider_manager.update_key(self._provider_metadata)
        if not resolution:
            return False

        generation = self._start_init_attempt("Updating API key.")
        if not self._apply_provider_resolution(resolution, generation=generation):
            return False
        return self._initialize_client(
            announce=True,
            on_success=on_success,
            generation=generation,
        )

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
        with self._query_lock:
            self._set_last_query_error(None)
            label = progress_label or self.provider_label
            # Snapshot the client exactly once. A concurrent lifecycle change
            # may affect the next query, but cannot turn a second property read
            # in this request into ``None.stream``.
            client = self.client
            if client is None:
                reason = self.api_error_reason or f"{label} client is not configured."
                self._set_last_query_error(reason)
                self._ui.error(f"Cannot query AI provider: {reason}")
                self._ui.info("AI-powered suggestions are disabled. Retry provider setup to continue.")
                return "", {}

            metrics: Dict[str, Any] = {}
            full_text = ""

            interactive = getattr(self, "_interactive", True)
            stdin_context = _suppress_stdin_echo() if interactive else nullcontext()
            progress_context = Progress() if interactive else nullcontext(None)
            with stdin_context, progress_context as progress:
                task = (
                    progress.add_task(f"[cyan]Querying {label}...", total=None)
                    if progress is not None
                    else None
                )

                chunks: List[str] = []
                generator = None
                try:
                    generator = client.stream(prompt)
                    while True:
                        try:
                            text = next(generator)
                            chunks.append(text)
                            if progress is not None and task is not None:
                                progress.advance(task)
                        except StopIteration as e:
                            metrics = e.value if e.value else {}
                            break
                except Exception as e:
                    # Also catch providers that fail while constructing a stream.
                    self._set_last_query_error(
                        str(e).strip() or f"{label} request failed."
                    )
                    handled = False
                    if on_exception:
                        handled = on_exception(e, label)
                    if not handled:
                        classified = self._classify_provider_error(self.provider, e)
                        if classified is not None:
                            category, reason = classified
                            self._set_last_query_error(reason)
                            if category == "transient":
                                self._ui.error(reason)
                            else:
                                self._enter_degraded_mode(reason)
                                self._ui.error(f"{label} is unavailable: {reason}")
                            handled = True
                    if not handled:
                        self._ui.error(f"Error during {label} stream: {e}")
                    if generator is not None:
                        generator.close()
                    if not metrics:
                        metrics = {'ttft': -1, 'tps': -1, 'tokens_out': -1}
                    self._ui.display_metrics(metrics)
                    return "", metrics
                finally:
                    if progress is not None and task is not None:
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
        classified = self._classify_provider_error(self.provider, exc)
        if classified is None:
            return False

        category, reason = classified
        self._set_last_query_error(reason)
        if category == "transient":
            self._ui.error(reason, with_panel=True)
            return True

        self._enter_degraded_mode(reason)

        if category == "region_blocked":
            self._ui.error(
                "Google Gemini rejected the request because your current region is not supported.\n"
                "Switch to another provider (Anthropic Claude is recommended) or retry from a supported location.",
                with_panel=True,
            )
            if not getattr(self, "_interactive", True):
                return True
            options = [
                ("switch", "Switch provider (Claude recommended)"),
                ("settings", "Open AI settings"),
                ("skip", "Return to main menu"),
            ]
            title = "Gemini is region-locked here. How should we proceed?"
            instructions = "Choose 'switch' to continue without Gemini."
        else:
            self._ui.error(
                f"{provider_label} is unavailable: {reason}\n"
                "Update the API key, switch providers, or retry setup after fixing the account issue.",
                with_panel=True,
            )
            if not getattr(self, "_interactive", True):
                return True
            options = [
                ("retry", "Retry provider setup now"),
                ("switch", "Switch provider"),
                ("settings", "Open AI settings"),
                ("skip", "Return to main menu"),
            ]
            title = f"{provider_label} needs attention. How should we proceed?"
            instructions = "Choose 'retry' after fixing credentials, billing, or quota."

        try:
            choice = self._ui.interactive_menu(title, options, instructions)
        except KeyboardInterrupt:
            return True

        if choice == "retry":
            self.reconfigure(on_success=on_switch_success)
        elif choice == "switch":
            self.change_provider_interactive(on_success=on_switch_success)
        elif choice == "settings":
            if on_settings:
                on_settings()

        return True

    # -------------------------------------------------------------------------
    # Usage Tracking
    # -------------------------------------------------------------------------

    def record_usage(self, usage: Optional[Dict[str, int]]) -> None:
        """Aggregate per-session token usage for the exit summary."""
        if not usage:
            return
        with self._usage_lock:
            self._session_requests += 1
            for key, value in usage.items():
                if value is None:
                    continue
                self._session_usage[key] = self._session_usage.get(key, 0) + int(value)

    def format_token_summary(self) -> str:
        """Format session token usage for display."""
        with self._usage_lock:
            tokens = {k: v for k, v in self._session_usage.items() if v}
            request_count = self._session_requests
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

        prefix = f"Sessions: {request_count} | " if request_count else ""
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
