from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
import logging
import os
from typing import Any, Dict, Optional, Tuple


class _SuppressGenAIWarnings(logging.Filter):
    """Filter noisy SDK warnings about non-text parts."""

    MESSAGE_SNIPPETS = (
        "non-text parts in the response",
    )

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        msg = record.getMessage()
        return not any(snippet in msg for snippet in self.MESSAGE_SNIPPETS)


for _logger_name in ("google.genai", "google_genai.types"):
    logging.getLogger(_logger_name).addFilter(_SuppressGenAIWarnings())


_PROVIDER_DISCOVERY_ORDER: Tuple[Tuple[str, str, str], ...] = (
    ("gemini", "GEMINI_API_KEY", "gemini_api_key"),
    ("claude", "ANTHROPIC_API_KEY", "anthropic_api_key"),
)


def _resolve_model_name(env_var: str, default: str) -> str:
    from vocab_builder.compat import get_env

    configured = get_env(env_var)
    if configured is None:
        return default
    stripped = configured.strip()
    return stripped or default


def _candidate_env_paths() -> Tuple[Path, ...]:
    from vocab_builder.compat import config_homes_for_read, get_env, runtime_root
    candidates = []
    config_dir = get_env("VOCABBUILDER_CONFIG_DIR")
    if config_dir:
        candidates.append(Path(config_dir).expanduser() / ".env")
    source_root = Path(__file__).resolve().parent.parent
    candidates.append(runtime_root(source_root) / ".env")
    for config_dir in config_homes_for_read():
        candidates.append(config_dir / ".env")

    deduped = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return tuple(deduped)


def _read_env_file_value(path: Path, env_var: str) -> Optional[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() != env_var:
            continue
        cleaned = value.strip().strip("'\"")
        if cleaned:
            return cleaned
    return None


def _keyring_get_password_best_effort(service: str, name: str) -> Optional[str]:
    from vocab_builder.compat import KEYRING_SERVICE, keyring_get_with_fallback

    try:
        import keyring  # type: ignore[import]
    except ImportError:
        return None

    try:
        if service == KEYRING_SERVICE:
            value, _service = keyring_get_with_fallback(name)
            return value
        return keyring.get_password(service, name)
    except Exception:
        return None


def _display_provider_name(provider_name: str) -> str:
    mapping = {
        "gemini": "Google Gemini",
        "claude": "Anthropic Claude",
    }
    return mapping.get(provider_name.lower(), provider_name)


def classify_provider_error(provider_name: str, exc: Exception) -> Optional[Tuple[str, str]]:
    """Return (category, user-facing reason) for known provider failures."""
    provider_key = (provider_name or "").strip().lower()
    message = str(exc) or exc.__class__.__name__
    lower = message.lower()
    display_name = _display_provider_name(provider_key)

    if provider_key == "gemini":
        if GeminiClient._is_region_block_error(exc):
            return "region_blocked", "Gemini is blocked in this region (FAILED_PRECONDITION)."
        if GeminiClient._is_leaked_key_error(exc):
            return "auth", GeminiClient._LEAKED_KEY_MESSAGE

    auth_markers = (
        "invalid api key",
        "api key not valid",
        "authentication",
        "unauthorized",
        "unauthenticated",
        "forbidden",
        "permission denied",
        "permission_denied",
        "invalid x-api-key",
        "api key rejected",
        "revoked",
    )
    quota_markers = (
        "insufficient_quota",
        "quota exceeded",
        "quota has been exceeded",
        "resource exhausted",
        "quota",
    )
    billing_markers = (
        "billing",
        "payment required",
        "insufficient funds",
        "credit balance",
    )

    if any(marker in lower for marker in auth_markers):
        return "auth", f"{display_name} credentials were rejected or revoked."
    if any(marker in lower for marker in billing_markers):
        return "billing", f"{display_name} billing is preventing requests."
    if any(marker in lower for marker in quota_markers):
        return "quota", f"{display_name} quota is exhausted or unavailable."
    return None


class LLMClient(ABC):
    @abstractmethod
    def stream(self, prompt: str, *, thinking_level: str = "low"):
        """Yield chunks of pure text.

        Args:
            prompt: The text prompt to send to the model.
            thinking_level: Reasoning depth - "low" for simple tasks (vocabulary),
                           "medium" for moderate complexity (translation).
        """
        ...

    def model_label(self) -> str:
        """Return a human-readable provider/model label."""
        return self.__class__.__name__

    def verify_credentials(self, timeout: float = 5.0) -> None:  # pragma: no cover - optional override
        """Validate credentials; subclasses may override for richer checks."""
        return None

class GeminiClient(LLMClient):
    MODEL_NAME = "gemini-3-flash-preview"
    _LEAKED_KEY_MESSAGE = (
        "Your Gemini API key has been revoked by Google (flagged as leaked). "
        "This usually means the key was exposed in a public place (e.g., GitHub). "
        "Generate a NEW key at https://aistudio.google.com/apikey"
    )
    _REGION_BLOCK_MESSAGE = (
        "Gemini is not available in your current region. "
        "Choose a different provider or try from a supported location."
    )

    @dataclass(frozen=True)
    class _StreamState:
        ttft: float
        t_first: float
        pieces: list[str]
        usage_metadata: Any | None

    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        # Lazy import to avoid heavy SDK cost at process startup.
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=key)
        self._model_name = _resolve_model_name(
            "VOCABBUILDER_GEMINI_MODEL",
            self.MODEL_NAME,
        )

    def _maybe_raise_mapped_error(self, exc: Exception) -> None:
        if self._is_leaked_key_error(exc):
            raise RuntimeError(self._LEAKED_KEY_MESSAGE) from exc
        if self._is_region_block_error(exc):
            raise RuntimeError(self._REGION_BLOCK_MESSAGE) from exc

    def _resolve_thinking_level(self, thinking_level: str):
        level_map = {
            "low": self._types.ThinkingLevel.LOW,
            "medium": self._types.ThinkingLevel.MEDIUM,
            "high": self._types.ThinkingLevel.HIGH,
        }
        return level_map.get(thinking_level.strip().lower(), self._types.ThinkingLevel.LOW)

    def _build_prompt_contents(self, prompt: str):
        return [
            self._types.Content(
                role="user",
                parts=[self._types.Part.from_text(text=prompt)],
            )
        ]

    def _build_generate_content_config(self, sdk_level):
        return self._types.GenerateContentConfig(
            response_mime_type="text/plain",
            temperature=1.0,  # Recommended for Gemini 3 models
            max_output_tokens=8192,
            thinking_config=self._types.ThinkingConfig(thinking_level=sdk_level),
        )

    def _create_stream(self, client: Any, model_name: str, contents: Any, cfg: Any):
        try:
            return client.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=cfg,
            )
        except Exception as exc:
            self._maybe_raise_mapped_error(exc)
            raise

    def _yield_text_and_collect(self, stream: Any, t0: float):
        pieces: list[str] = []
        usage_metadata: Any | None = None

        try:
            first_chunk = next(stream)
        except StopIteration:
            t_first = perf_counter()
            ttft = t_first - t0
            logging.getLogger(__name__).warning("Gemini returned no tokens.")
            return self._StreamState(
                ttft=ttft, t_first=t_first, pieces=pieces, usage_metadata=usage_metadata
            )
        except Exception as exc:
            self._maybe_raise_mapped_error(exc)
            raise

        t_first = perf_counter()
        ttft = t_first - t0

        first_text = first_chunk.text or ""
        pieces.append(first_text)
        yield first_text
        usage_metadata = getattr(first_chunk, "usage_metadata", None) or usage_metadata

        for chunk in stream:
            chunk_text = chunk.text or ""
            if chunk_text:
                pieces.append(chunk_text)
                yield chunk_text

            chunk_usage = getattr(chunk, "usage_metadata", None)
            if chunk_usage is not None:
                usage_metadata = chunk_usage

        return self._StreamState(ttft=ttft, t_first=t_first, pieces=pieces, usage_metadata=usage_metadata)

    @staticmethod
    def _maybe_get_stream_response(stream: Any) -> Any | None:
        response_attr = getattr(stream, "response", None)
        if response_attr is None:
            return None
        if callable(response_attr):
            try:
                return response_attr()
            except Exception:
                return None
        return response_attr

    def _merge_usage_metadata(self, usage_metadata: Any | None, stream: Any) -> Any | None:
        final_response = self._maybe_get_stream_response(stream)
        if final_response is None:
            return usage_metadata
        final_usage = getattr(final_response, "usage_metadata", None)
        return final_usage or usage_metadata

    def _usage_summary_from_metadata(self, usage_metadata: Any | None) -> Dict[str, int]:
        if usage_metadata is None:
            return {}
        return self._extract_usage_counts(usage_metadata)

    def _count_tokens_best_effort(self, client: Any, model_name: str, text: str) -> int:
        try:
            token_payload = [
                self._types.Content(
                    role="user",
                    parts=[self._types.Part.from_text(text=text)],
                )
            ]
            token_info = client.models.count_tokens(model=model_name, contents=token_payload)
        except Exception as exc:
            logging.getLogger(__name__).error("Failed to count tokens: %s", exc)
            return 0
        return int(getattr(token_info, "total_tokens", 0) or 0)

    def _resolve_output_tokens(
        self,
        client: Any,
        model_name: str,
        usage_summary: Dict[str, int],
        full_text: str,
    ) -> tuple[int, Dict[str, int]]:
        out_tokens = int(usage_summary.get("output_tokens", 0) or 0)
        if out_tokens:
            return out_tokens, usage_summary
        if not full_text:
            return 0, usage_summary

        out_tokens = self._count_tokens_best_effort(client, model_name, full_text)
        if not out_tokens:
            return 0, usage_summary

        updated_usage = dict(usage_summary) if usage_summary else {}
        updated_usage.setdefault("output_tokens", out_tokens)
        updated_usage.setdefault("total_tokens", out_tokens)
        return out_tokens, updated_usage

    @staticmethod
    def _compute_tps(out_tokens: int, t_first: float, t_last: float) -> float:
        duration = max(t_last - t_first, 1e-9) if t_first else 1e-9
        return (out_tokens / duration) if out_tokens else 0.0

    @staticmethod
    def _build_metrics(
        ttft: float,
        out_tokens: int,
        tps: float,
        usage_summary: Dict[str, int],
    ) -> Dict[str, Any]:
        metrics: Dict[str, Any] = dict(ttft=ttft, tokens_out=out_tokens, tps=tps)
        if usage_summary:
            metrics["usage"] = usage_summary
        return metrics

    def stream(self, prompt: str, *, thinking_level: str = "low"):
        """
        Yields chunks of text while calculating TTFT and TPS.

        Args:
            prompt: The text prompt to send to the model.
            thinking_level: Reasoning depth - "low" for simple tasks,
                           "medium" for moderate complexity.

        Returns a dictionary with performance metrics upon generator completion.
        Example return: {'ttft': 0.5, 'tps': 50.0, 'tokens_out': 100, 'usage': {...}}
        """
        client = self._client
        model_name = self._model_name

        t0 = perf_counter()
        sdk_level = self._resolve_thinking_level(thinking_level)
        contents = self._build_prompt_contents(prompt)
        cfg = self._build_generate_content_config(sdk_level)
        stream = self._create_stream(client, model_name, contents, cfg)

        state = yield from self._yield_text_and_collect(stream, t0)
        t_last = perf_counter()

        usage_metadata = self._merge_usage_metadata(state.usage_metadata, stream)
        usage_summary = self._usage_summary_from_metadata(usage_metadata)
        full_text = "".join(state.pieces)
        out_tokens, usage_summary = self._resolve_output_tokens(client, model_name, usage_summary, full_text)
        tps = self._compute_tps(out_tokens, state.t_first, t_last)
        return self._build_metrics(state.ttft, out_tokens, tps, usage_summary)

    def model_label(self) -> str:
        return f"Google Gemini ({self._model_name})"

    def verify_credentials(self, timeout: float = 5.0) -> None:
        def _probe() -> None:
            payload = [
                self._types.Content(
                    role="user",
                    parts=[self._types.Part.from_text(text="credential-check")],
                )
            ]
            self._client.models.count_tokens(model=self._model_name, contents=payload)

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_probe)
        try:
            future.result(timeout=timeout)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise TimeoutError("Gemini validation timed out") from exc
        except Exception as exc:
            if self._is_leaked_key_error(exc):
                raise RuntimeError(
                    "Your Gemini API key has been revoked by Google (flagged as leaked). "
                    "This usually means the key was exposed in a public place (e.g., GitHub). "
                    "Generate a NEW key at https://aistudio.google.com/apikey"
                ) from exc
            if self._is_region_block_error(exc):
                raise RuntimeError(
                    "Gemini is not available in your current region (FAILED_PRECONDITION). "
                    "Choose a different provider (e.g., Claude) or try again from a supported location."
                ) from exc
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _extract_usage_counts(usage: Any) -> Dict[str, int]:
        """Convert SDK usage metadata to a plain dict of token counters."""
        fields = {
            "prompt_tokens": ("prompt_token_count",),
            "output_tokens": ("candidates_token_count", "response_token_count"),
            "total_tokens": ("total_token_count",),
            "thoughts_tokens": ("thoughts_token_count",),
            "tool_tokens": ("tool_use_prompt_token_count",),
            "cached_tokens": ("cached_content_token_count",),
        }

        summary: Dict[str, int] = {}
        for label, attr_names in fields.items():
            for attr in attr_names:
                value = getattr(usage, attr, None)
                if value is not None:
                    summary[label] = int(value)
                    break
        return summary

    @staticmethod
    def _is_region_block_error(exc: Exception) -> bool:
        """Detect Gemini geo restrictions from error text."""
        msg = str(exc).lower()
        return "location is not supported" in msg or "failed_precondition" in msg

    @staticmethod
    def _is_leaked_key_error(exc: Exception) -> bool:
        """Detect when Google has flagged an API key as leaked/compromised."""
        msg = str(exc).lower()
        return "leaked" in msg or (
            "permission_denied" in msg and "api key" in msg
        )

class ClaudeClient(LLMClient):
    MODEL_NAME = "claude-sonnet-4-6"

    def __init__(self, api_key: str | None = None):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "The anthropic package is not installed. "
                "To use Claude, install it with: pip install anthropic"
            ) from exc

        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=key)
        self._model_name = _resolve_model_name(
            "VOCABBUILDER_CLAUDE_MODEL",
            self.MODEL_NAME,
        )

    def stream(self, prompt: str, *, thinking_level: str = "low"):
        # Claude doesn't use thinking_level; parameter accepted for interface compatibility
        t0 = perf_counter()
        t_first = 0.0
        pieces: list[str] = []

        with self._client.messages.stream(
            model=self._model_name,
            max_tokens=8192,
            temperature=0.1,
            messages=[
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ],
        ) as stream:
            for text in stream.text_stream:
                if not t_first:
                    t_first = perf_counter()
                pieces.append(text)
                yield text

            # Collect usage from the final message
            final_message = stream.get_final_message()

        ttft = (t_first - t0) if t_first else (perf_counter() - t0)
        usage_summary: Dict[str, int] = {}
        if final_message and getattr(final_message, "usage", None):
            usage = final_message.usage
            if getattr(usage, "input_tokens", None) is not None:
                usage_summary["prompt_tokens"] = usage.input_tokens
            if getattr(usage, "output_tokens", None) is not None:
                usage_summary["output_tokens"] = usage.output_tokens
                usage_summary["total_tokens"] = (
                    usage_summary.get("prompt_tokens", 0) + usage.output_tokens
                )

        out_tokens = usage_summary.get("output_tokens", 0)
        duration = (perf_counter() - t_first) if t_first else 1e-9
        tps = out_tokens / max(duration, 1e-9)

        metrics: Dict[str, Any] = dict(ttft=ttft, tokens_out=out_tokens, tps=tps)
        if usage_summary:
            metrics["usage"] = usage_summary
        return metrics

    def model_label(self) -> str:
        return f"Anthropic Claude ({self._model_name})"

    def verify_credentials(self, timeout: float = 5.0) -> None:
        def _probe() -> None:
            self._client.models.list()

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_probe)
        try:
            future.result(timeout=timeout)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise TimeoutError("Claude validation timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


class ProviderFactory:
    """Factory to create different LLM client implementations."""

    @staticmethod
    def create(provider_name: str, api_key: Optional[str] = None) -> LLMClient:
        """
        Create an LLM client based on the provider name.
        
        Args:
            provider_name: Name of the LLM provider ("gemini" or "claude")
            api_key: Optional API key override
            
        Returns:
            An LLMClient implementation
            
        Raises:
            ValueError: If the provider name is unknown
        """
        provider_name = provider_name.lower()
        
        if provider_name == "gemini":
            return GeminiClient(api_key)
        elif provider_name == "claude":
            return ClaudeClient(api_key)
        else:
            raise ValueError(f"Unknown provider: {provider_name}")

    @staticmethod
    def available_providers() -> Tuple[str, ...]:
        """Return the supported provider identifiers in priority order."""
        return tuple(provider for provider, _, _ in _PROVIDER_DISCOVERY_ORDER)

    @staticmethod
    def default_provider() -> str:
        """Return the default provider name based on environment."""
        for provider_name, env_var, _ in _PROVIDER_DISCOVERY_ORDER:
            if os.getenv(env_var):
                return provider_name

        pytest_active = bool(os.getenv("PYTEST_CURRENT_TEST"))
        from vocab_builder.compat import get_env as _get_env
        allow_persistent_autodetect = bool(_get_env("VOCABBUILDER_TEST_PROVIDER_AUTODETECT"))
        if pytest_active and not allow_persistent_autodetect:
            return "gemini"

        for path in _candidate_env_paths():
            if not path.exists():
                continue
            for provider_name, env_var, _ in _PROVIDER_DISCOVERY_ORDER:
                if _read_env_file_value(path, env_var):
                    return provider_name

        for provider_name, _, keyring_name in _PROVIDER_DISCOVERY_ORDER:
            from vocab_builder.compat import KEYRING_SERVICE as _KR_SVC
            stored = _keyring_get_password_best_effort(_KR_SVC, keyring_name)
            if stored:
                return provider_name

        return "gemini"
