from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from time import perf_counter
import logging
import os
from typing import Any, Dict, Optional


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

    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        # Lazy import to avoid heavy SDK cost at process startup.
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=key)

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
        model_name = self.MODEL_NAME

        # Map string level to SDK enum
        level_map = {
            "low": self._types.ThinkingLevel.LOW,
            "medium": self._types.ThinkingLevel.MEDIUM,
            "high": self._types.ThinkingLevel.HIGH,
        }
        sdk_level = level_map.get(thinking_level.lower(), self._types.ThinkingLevel.LOW)

        t0 = perf_counter()
        contents = [
            self._types.Content(
                role="user",
                parts=[self._types.Part.from_text(text=prompt)]
            )
        ]
        cfg = self._types.GenerateContentConfig(
            response_mime_type="text/plain",
            temperature=1.0,  # Recommended for Gemini 3 models
            max_output_tokens=8192,
            thinking_config=self._types.ThinkingConfig(
                thinking_level=sdk_level
            ),
        )

        try:
            stream = client.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=cfg,
            )
        except Exception as exc:
            if self._is_leaked_key_error(exc):
                raise RuntimeError(
                    "Your Gemini API key has been revoked by Google (flagged as leaked). "
                    "This usually means the key was exposed in a public place (e.g., GitHub). "
                    "Generate a NEW key at https://aistudio.google.com/apikey"
                ) from exc
            if self._is_region_block_error(exc):
                raise RuntimeError(
                    "Gemini is not available in your current region. "
                    "Choose a different provider or try from a supported location."
                ) from exc
            raise

        t_first = 0.0
        ttft = 0.0
        pieces = []
        first_chunk_yielded = False
        usage_metadata: Optional[Any] = None

        try:
            first_chunk = next(stream)
            t_first = perf_counter()
            ttft = t_first - t0
            first_chunk_text = first_chunk.text or ""
            pieces.append(first_chunk_text)
            yield first_chunk_text
            first_chunk_yielded = True
            usage_metadata = getattr(first_chunk, "usage_metadata", None) or usage_metadata

            for chunk in stream:
                chunk_text = chunk.text or ""
                if chunk_text:
                    pieces.append(chunk_text)
                    yield chunk_text
                if getattr(chunk, "usage_metadata", None):
                    usage_metadata = chunk.usage_metadata

        except StopIteration:
            if not first_chunk_yielded:
                t_first = perf_counter()
                ttft = t_first - t0
                print("[Warning] Model returned no tokens.")
                return dict(ttft=ttft, tps=0.0, tokens_out=0)
        except Exception as exc:
            if self._is_leaked_key_error(exc):
                raise RuntimeError(
                    "Your Gemini API key has been revoked by Google (flagged as leaked). "
                    "This usually means the key was exposed in a public place (e.g., GitHub). "
                    "Generate a NEW key at https://aistudio.google.com/apikey"
                ) from exc
            if self._is_region_block_error(exc):
                raise RuntimeError(
                    "Gemini is not available in your current region. "
                    "Choose a different provider or try from a supported location."
                ) from exc
            raise
        finally:
            t_last = perf_counter()
            full_text = "".join(pieces)

            final_response = None
            try:
                final_response = getattr(stream, "response", None)
                if callable(final_response):
                    final_response = final_response()
            except Exception:
                final_response = None

            if final_response is not None:
                usage_metadata = getattr(final_response, "usage_metadata", None) or usage_metadata

            usage_summary: Dict[str, int] = {}
            if usage_metadata is not None:
                usage_summary = self._extract_usage_counts(usage_metadata)

            out_tokens = usage_summary.get("output_tokens", 0)
            if not out_tokens and full_text:
                try:
                    token_payload = [
                        self._types.Content(
                            role="user",
                            parts=[self._types.Part.from_text(text=full_text)],
                        )
                    ]
                    token_info = client.models.count_tokens(
                        model=model_name,
                        contents=token_payload,
                    )
                    out_tokens = getattr(token_info, "total_tokens", 0)
                except Exception as e:
                    print(f"[Error] Failed to count tokens: {e}")
            if out_tokens:
                if not usage_summary:
                    usage_summary = {}
                usage_summary.setdefault("output_tokens", out_tokens)
                usage_summary.setdefault("total_tokens", out_tokens)

            duration = t_last - t_first if t_first > 0 else 1e-9
            duration = duration or 1e-9
            tps = out_tokens / duration

        metrics: Dict[str, Any] = dict(
            ttft=ttft,
            tokens_out=out_tokens,
            tps=tps,
        )
        if usage_summary:
            metrics["usage"] = usage_summary

        return metrics

    def model_label(self) -> str:
        return f"Google Gemini ({self.MODEL_NAME})"

    def verify_credentials(self, timeout: float = 5.0) -> None:
        def _probe() -> None:
            payload = [
                self._types.Content(
                    role="user",
                    parts=[self._types.Part.from_text(text="credential-check")],
                )
            ]
            self._client.models.count_tokens(model=self.MODEL_NAME, contents=payload)

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
    MODEL_NAME = "claude-3-5-sonnet-20240620"

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

    def stream(self, prompt: str, *, thinking_level: str = "low"):
        # Claude doesn't use thinking_level; parameter accepted for interface compatibility
        t0 = perf_counter()
        t_first = 0.0
        pieces: list[str] = []

        with self._client.messages.stream(
            model=self.MODEL_NAME,
            max_tokens=8192,
            temperature=0.1,
            messages=[
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ],
            extra_headers={
                "anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15"
            },
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
        return f"Anthropic Claude ({self.MODEL_NAME})"

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
    def default_provider() -> str:
        """Return the default provider name based on environment."""
        if os.getenv("GEMINI_API_KEY"):
            return "gemini"
        elif os.getenv("ANTHROPIC_API_KEY"):
            return "claude"
        else:
            return "gemini"  # Default to Gemini 
