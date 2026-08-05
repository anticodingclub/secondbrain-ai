"""Language model providers."""

from __future__ import annotations

from app.core.config import LLMProviderName, Settings
from app.services.llm.base import (
    CompletionChunk,
    LLMProvider,
    LLMUnavailableError,
    Message,
    Role,
)
from app.services.llm.providers import (
    AnthropicProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
)

__all__ = [
    "AnthropicProvider",
    "CompletionChunk",
    "GeminiProvider",
    "LLMProvider",
    "LLMUnavailableError",
    "Message",
    "OllamaProvider",
    "OpenAIProvider",
    "Role",
    "build_llm_provider",
]


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Pick a provider from configuration.

    A missing API key is not raised here. The application must still start —
    uploads, parsing and search all work without an LLM, and only chat needs
    one. The provider reports itself unhealthy instead, and the chat endpoint
    returns a 503 naming what to configure.
    """
    match settings.llm_provider:
        case LLMProviderName.OLLAMA:
            return OllamaProvider(model=settings.llm_model, base_url=settings.ollama_base_url)
        case LLMProviderName.OPENAI:
            return OpenAIProvider(
                model=settings.llm_model,
                base_url="https://api.openai.com/v1",
                api_key=settings.openai_api_key,
            )
        case LLMProviderName.ANTHROPIC:
            return AnthropicProvider(
                model=settings.llm_model,
                base_url="https://api.anthropic.com",
                api_key=settings.anthropic_api_key,
            )
        case LLMProviderName.GEMINI:
            return GeminiProvider(
                model=settings.llm_model,
                base_url="https://generativelanguage.googleapis.com/v1beta",
                api_key=settings.gemini_api_key,
            )
        case unsupported:  # pragma: no cover - guarded by the settings enum
            raise NotImplementedError(f"Unknown LLM provider: {unsupported!r}")
