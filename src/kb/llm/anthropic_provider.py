"""Anthropic structured-output provider via native tool use (HC-1.1).

Credentials come exclusively from the ``ANTHROPIC_API_KEY`` environment
variable (HC-5.3). Transient API failures are retried with exponential
backoff and jitter (spec §10); validation failures trigger corrective
re-prompts (spec §7.2).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, cast

import anthropic
from pydantic import BaseModel, ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from kb.errors import KBError
from kb.llm.base import LLMProvider, T

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-5"
_TOOL_NAME = "emit_structured_output"
_MAX_CORRECTIVE_ATTEMPTS = 2  # spec §7.2


def _is_transient(exc: BaseException) -> bool:
    """Retry only 429/5xx/network errors; never auth or validation errors (§10)."""
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    return isinstance(exc, anthropic.APIStatusError) and (
        exc.status_code == 429 or exc.status_code >= 500
    )


class AnthropicLLMProvider(LLMProvider):
    """Structured outputs through Anthropic's forced tool use."""

    def __init__(self, model: str = _DEFAULT_MODEL) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise KBError(
                "ANTHROPIC_API_KEY is not set — required for the Anthropic provider "
                "(see .env.example)"
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        """The Anthropic model ID in use (configurable via ``KB_LLM_MODEL``, spec §9)."""
        return self._model

    def generate_structured(self, *, system: str, prompt: str, schema: type[T]) -> T:
        """Call the model and validate; re-prompt with errors on invalid output (§7.2)."""
        current_prompt = prompt
        last_error = "no attempts made"
        for _ in range(1 + _MAX_CORRECTIVE_ATTEMPTS):
            raw = self._request(system=system, prompt=current_prompt, schema=schema)
            try:
                return schema.model_validate(raw)
            except ValidationError as exc:
                last_error = str(exc)
                logger.warning("structured output failed validation, re-prompting: %s", exc)
                current_prompt = (
                    f"{prompt}\n\n"
                    "Your previous response failed schema validation.\n"
                    f"Previous response (JSON):\n{json.dumps(raw, ensure_ascii=False)}\n\n"
                    f"Validation errors:\n{exc}\n\n"
                    "Return a corrected response that satisfies the schema exactly."
                )
        raise KBError(
            f"structured output failed validation after {1 + _MAX_CORRECTIVE_ATTEMPTS} "
            f"attempts: {last_error}"
        )

    @retry(
        retry=retry_if_exception(_is_transient),
        wait=wait_random_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _request(self, *, system: str, prompt: str, schema: type[BaseModel]) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "name": _TOOL_NAME,
                    "description": "Emit the structured result. Always call this tool.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )
        for block in response.content:
            if block.type == "tool_use" and isinstance(block.input, dict):
                return cast("dict[str, Any]", block.input)
        raise KBError("Anthropic response contained no structured tool output")
