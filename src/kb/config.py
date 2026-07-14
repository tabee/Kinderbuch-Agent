"""Runtime configuration from environment variables, read once at startup (spec §9).

Provider credentials (``ANTHROPIC_API_KEY``, ``GOOGLE_APPLICATION_CREDENTIALS``)
are deliberately *not* read here — they live inside the concrete providers (HC-5.3).
"""

from __future__ import annotations

import os

from pydantic import BaseModel

from kb.errors import KBError

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseModel):
    """Non-secret application settings."""

    llm_provider: str = "anthropic"
    llm_model: str | None = None  # None → provider default
    llm_temperature: float | None = None  # None → provider default; 0.0 focused … 1.0 varied
    image_provider: str = "mock"
    image_model: str | None = None  # None → provider default
    max_concurrency: int = 4
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from the environment, failing fast on invalid values."""
        raw_concurrency = os.environ.get("KB_MAX_CONCURRENCY", "4")
        try:
            max_concurrency = int(raw_concurrency)
        except ValueError as exc:
            raise KBError(
                f"KB_MAX_CONCURRENCY must be an integer, got {raw_concurrency!r}"
            ) from exc
        if max_concurrency < 1:
            raise KBError(f"KB_MAX_CONCURRENCY must be >= 1, got {max_concurrency}")

        log_level = os.environ.get("KB_LOG_LEVEL", "INFO").upper()
        if log_level not in _LOG_LEVELS:
            raise KBError(
                f"KB_LOG_LEVEL must be one of {', '.join(sorted(_LOG_LEVELS))}, got {log_level!r}"
            )

        raw_temperature = os.environ.get("KB_LLM_TEMPERATURE", "").strip()
        llm_temperature: float | None = None
        if raw_temperature:
            try:
                llm_temperature = float(raw_temperature)
            except ValueError as exc:
                raise KBError(
                    f"KB_LLM_TEMPERATURE must be a number between 0.0 and 1.0, "
                    f"got {raw_temperature!r}"
                ) from exc
            if not 0.0 <= llm_temperature <= 1.0:
                raise KBError(
                    f"KB_LLM_TEMPERATURE must be between 0.0 and 1.0, got {llm_temperature}"
                )

        return cls(
            llm_provider=os.environ.get("KB_LLM_PROVIDER", "anthropic"),
            llm_model=os.environ.get("KB_LLM_MODEL") or None,
            llm_temperature=llm_temperature,
            image_provider=os.environ.get("KB_IMAGE_PROVIDER", "mock"),
            image_model=os.environ.get("KB_IMAGE_MODEL") or None,
            max_concurrency=max_concurrency,
            log_level=log_level,
        )
