from abc import ABC, abstractmethod
from time import perf_counter
import os
# Fix the imports for Google Generative AI
from google import genai
from google.genai import types


class LLMClient(ABC):
    @abstractmethod
    def stream(self, prompt: str):
        """Yield chunks of pure text."""
        ...

    def model_label(self) -> str:
        """Return a human-readable provider/model label."""
        return self.__class__.__name__

class GeminiClient(LLMClient):
    MODEL_NAME = "gemini-flash-latest"

    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self._client = genai.Client(api_key=key)

    def stream(self, prompt: str):
        """
        Yields chunks of text while calculating TTFT and TPS.

        Returns a dictionary with performance metrics upon generator completion.
        Example return: {'ttft': 0.5, 'tps': 50.0, 'tokens_out': 100}
        """
        client = self._client
        model_name = self.MODEL_NAME

        t0 = perf_counter()
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)]
            )
        ]
        cfg = types.GenerateContentConfig(
            response_mime_type="text/plain",
            thinking_config=types.ThinkingConfig(thinking_budget=-1),
        )

        stream = client.models.generate_content_stream(
            model=model_name,
            contents=contents,
            config=cfg,
        )

        t_first = 0.0
        ttft = 0.0
        pieces = []
        first_chunk_yielded = False

        try:
            first_chunk = next(stream)
            t_first = perf_counter()
            ttft = t_first - t0
            first_chunk_text = first_chunk.text or ""
            pieces.append(first_chunk_text)
            yield first_chunk_text
            first_chunk_yielded = True

            for chunk in stream:
                chunk_text = chunk.text or ""
                if chunk_text:
                    pieces.append(chunk_text)
                    yield chunk_text

        except StopIteration:
            if not first_chunk_yielded:
                t_first = perf_counter()
                ttft = t_first - t0
                print("[Warning] Model returned no tokens.")
                return dict(ttft=ttft, tps=0.0, tokens_out=0)
            pass

        finally:
            t_last = perf_counter()
            full_text = "".join(pieces)

            out_tokens = 0
            if full_text:
                try:
                    token_info = client.models.count_tokens(
                        model=model_name,
                        contents=full_text
                    )
                    out_tokens = token_info.total_tokens
                except Exception as e:
                    print(f"[Error] Failed to count tokens: {e}")

            duration = t_last - t_first if t_first > 0 else 1e-9
            duration = duration or 1e-9
            tps = out_tokens / duration

        return dict(
            ttft=ttft,
            tokens_out=out_tokens,
            tps=tps,
        )

    def model_label(self) -> str:
        return f"Google Gemini ({self.MODEL_NAME})"

# Optional Claude client implementation for backward compatibility
# To restore Claude support, users can simply switch to this client
try:
    import anthropic
    
    class ClaudeClient(LLMClient):
        MODEL_NAME = "claude-3-5-sonnet-20240620"
        
        def __init__(self, api_key: str | None = None):
            key = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            self._client = anthropic.Anthropic(api_key=key)
            
        def stream(self, prompt: str):
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
                    yield text

        def model_label(self) -> str:
            return f"Anthropic Claude ({self.MODEL_NAME})"
except ImportError:
    # If anthropic is not installed, provide a stub that raises an informative error
    class ClaudeClient(LLMClient):
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "The anthropic package is not installed. "
                "To use Claude, install it with: pip install anthropic"
            )
        
        def stream(self, prompt: str):
            yield ""

        def model_label(self) -> str:
            return "Anthropic Claude (unavailable)"

class ProviderFactory:
    """Factory to create different LLM client implementations."""
    
    @staticmethod
    def create(provider_name: str, api_key: str = None) -> LLMClient:
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
