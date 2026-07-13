"""LLM providers: abstract interface, mock implementation, and factory (HC-5.2)."""

from __future__ import annotations

from kb.config import Settings
from kb.errors import KBError
from kb.llm.base import LLMProvider
from kb.llm.mock import MockLLMProvider

__all__ = ["LLMProvider", "MockLLMProvider", "create_llm_provider"]


def create_llm_provider(settings: Settings, *, languages: list[str] | None = None) -> LLMProvider:
    """Instantiate the provider selected via ``KB_LLM_PROVIDER`` (spec §9)."""
    if settings.llm_provider == "mock":
        return MockLLMProvider(languages or ("en", "th"))
    if settings.llm_provider == "anthropic":
        from kb.llm.anthropic_provider import AnthropicLLMProvider

        if settings.llm_model:
            return AnthropicLLMProvider(model=settings.llm_model)
        return AnthropicLLMProvider()
    raise KBError(
        f"unknown LLM provider {settings.llm_provider!r} (expected 'anthropic' or 'mock')"
    )
