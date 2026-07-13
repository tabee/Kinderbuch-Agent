"""Structured-output validation loop tests (spec §7.2) — offline, no network."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from kb.errors import KBError
from kb.llm.anthropic_provider import AnthropicLLMProvider


class _Answer(BaseModel):
    value: int


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> AnthropicLLMProvider:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-no-network")
    return AnthropicLLMProvider()


def _fake_request(responses: list[dict[str, Any]]) -> tuple[Any, list[str]]:
    prompts: list[str] = []
    queue = list(responses)

    def fake(*, system: str, prompt: str, schema: type[BaseModel]) -> dict[str, Any]:
        prompts.append(prompt)
        return queue.pop(0)

    return fake, prompts


def test_corrective_reprompt_recovers_from_invalid_output(
    provider: AnthropicLLMProvider,
) -> None:
    """First response fails validation; the corrective re-prompt succeeds (§7.2)."""
    fake, prompts = _fake_request([{"value": "not-an-int"}, {"value": 7}])
    provider._request = fake  # type: ignore[method-assign]

    result = provider.generate_structured(system="s", prompt="question", schema=_Answer)

    assert result.value == 7
    assert len(prompts) == 2
    assert "failed schema validation" in prompts[1]  # errors are fed back to the model
    assert "question" in prompts[1]  # original task is preserved


def test_gives_up_after_two_corrective_attempts(provider: AnthropicLLMProvider) -> None:
    """1 initial + max 2 corrective attempts, then a clear failure (§7.2)."""
    fake, prompts = _fake_request([{"value": "a"}, {"value": "b"}, {"value": "c"}, {"value": 9}])
    provider._request = fake  # type: ignore[method-assign]

    with pytest.raises(KBError, match="failed validation after 3 attempts"):
        provider.generate_structured(system="s", prompt="question", schema=_Answer)

    assert len(prompts) == 3  # the fourth (valid) response is never requested
