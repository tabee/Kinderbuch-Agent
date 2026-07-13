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
    image_provider: str = "mock"
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

        return cls(
            llm_provider=os.environ.get("KB_LLM_PROVIDER", "anthropic"),
            llm_model=os.environ.get("KB_LLM_MODEL") or None,
            image_provider=os.environ.get("KB_IMAGE_PROVIDER", "mock"),
            max_concurrency=max_concurrency,
            log_level=log_level,
        )
