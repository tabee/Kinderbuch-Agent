"""Mock LLM provider tests: offline, deterministic, schema-valid (spec §9, §15)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from kb.config import Settings
from kb.errors import KBError
from kb.llm import MockLLMProvider, create_llm_provider


class _Scene(BaseModel):
    heading: str
    characters_present: list[str]
    status: Literal["todo", "text_done"] = "todo"


class _StoryPage(BaseModel):
    number: int
    text: dict[str, str]
    image_prompt: str | None = None
    image_path: Path | None = None
    scene: _Scene
    keywords: list[str] = Field(default_factory=list)


def test_mock_llm_fills_nested_schema() -> None:
    provider = MockLLMProvider(["en", "th"])
    page = provider.generate_structured(system="s", prompt="p", schema=_StoryPage)

    assert page.number == 1
    assert page.scene.status == "todo"
    assert page.scene.characters_present


def test_hc12_text_contains_every_configured_language() -> None:
    provider = MockLLMProvider(["en", "th"])
    page = provider.generate_structured(system="s", prompt="p", schema=_StoryPage)

    assert set(page.text) == {"en", "th"}
    assert "กาลครั้งหนึ่ง" in page.text["th"]  # real Thai text for the PDF gate (HC-3.4)


def test_mock_llm_is_deterministic() -> None:
    provider = MockLLMProvider(["en", "th"])
    first = provider.generate_structured(system="s", prompt="p", schema=_StoryPage)
    second = provider.generate_structured(system="other", prompt="other", schema=_StoryPage)

    assert first == second


def test_factory_selects_mock() -> None:
    settings = Settings(llm_provider="mock")
    assert isinstance(create_llm_provider(settings), MockLLMProvider)


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(KBError, match="unknown LLM provider"):
        create_llm_provider(Settings(llm_provider="gpt"))


def test_kb_llm_model_configures_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """KB_LLM_MODEL selects a cheaper model for development (spec §9). Offline: no API call."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-no-network")
    monkeypatch.setenv("KB_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("KB_LLM_MODEL", "claude-haiku-4-5")

    from kb.llm.anthropic_provider import AnthropicLLMProvider

    provider = create_llm_provider(Settings.from_env())

    assert isinstance(provider, AnthropicLLMProvider)
    assert provider.model == "claude-haiku-4-5"


def test_kb_llm_model_empty_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_LLM_MODEL", "")

    assert Settings.from_env().llm_model is None
