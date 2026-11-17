"""Provider factory: provider_type -> adapter instance."""

from __future__ import annotations

from llm.anthropic_provider import AnthropicProvider
from llm.base import BaseLLMProvider, LLMError
from llm.cli_provider import CliLLMProvider
from llm.gemini_provider import GeminiProvider
from llm.openai_compat import OpenAICompatibleProvider

#: provider_type -> adapter class. OpenAI-compatible vendors share one class.
PROVIDER_CLASSES: dict[str, type[BaseLLMProvider]] = {
    "gemini": GeminiProvider,
    "openai": OpenAICompatibleProvider,
    "openrouter": OpenAICompatibleProvider,
    "deepseek": OpenAICompatibleProvider,
    "custom": OpenAICompatibleProvider,
    "ollama": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
    "agy": CliLLMProvider,
    "codex": CliLLMProvider,
}


def create_provider(
    provider_type: str,
    api_key: str = "",
    base_url: str = "",
    timeout: float | None = None,
) -> BaseLLMProvider:
    """Build the adapter for ``provider_type``.

    OpenAI-compatible adapters need to know which vendor they are so they can
    pick the right default base URL and headers.
    """
    cls = PROVIDER_CLASSES.get(provider_type)
    if cls is None:
        raise LLMError(f"Unsupported provider type: {provider_type}")

    if cls in (OpenAICompatibleProvider, CliLLMProvider):
        return cls(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            provider_type=provider_type,
        )
    return cls(api_key=api_key, base_url=base_url, timeout=timeout)
