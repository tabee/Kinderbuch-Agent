"""Google image provider via the Gemini API (``KB_IMAGE_PROVIDER=imagen``).

Classic Imagen ``:predict`` models are closed to new users (verified 2026-07),
so this provider targets Gemini image models (default ``gemini-3.1-flash-image``)
through ``generateContent`` — which accepts reference images as input parts,
exactly what character consistency requires (HC-2.2/2.3).

Credentials come exclusively from the ``GOOGLE_API_KEY`` environment variable
(HC-5.3). Transient failures are retried with exponential backoff (spec §10).
Request building and response parsing are pure functions so they can be tested
offline; the network call itself is never exercised by tests (Gate 4).
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from kb.core.persistence import atomic_write_bytes
from kb.errors import KBError
from kb.image.base import ImageProvider

logger = logging.getLogger(__name__)

_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_MODEL = "gemini-3.1-flash-image"


def _is_transient(exc: BaseException) -> bool:
    """Retry only 429/5xx/network errors; never auth or validation errors (§10)."""
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and (
        exc.response.status_code == 429 or exc.response.status_code >= 500
    )


def _mime_type(data: bytes) -> str:
    return "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"


def build_request(prompt: str, references: Sequence[bytes]) -> dict[str, Any]:
    """Build the ``generateContent`` payload.

    Reference images come first, in salience order, so "reference image N" in
    the prompt (HC-2.3) maps to the N-th image part.
    """
    parts: list[dict[str, Any]] = [
        {
            "inlineData": {
                "mimeType": _mime_type(image),
                "data": base64.b64encode(image).decode("ascii"),
            }
        }
        for image in references
    ]
    parts.append({"text": prompt})
    return {
        "contents": [{"parts": parts}],
        "generationConfig": {"imageConfig": {"aspectRatio": "1:1"}},
    }


def extract_image(data: dict[str, Any]) -> bytes:
    """Return the first inline image from a ``generateContent`` response."""
    candidates = data.get("candidates") or []
    if candidates:
        for part in candidates[0].get("content", {}).get("parts", []):
            inline = part.get("inlineData")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    raise KBError(
        "Gemini response contained no image data "
        f"(finishReason: {candidates[0].get('finishReason') if candidates else 'no candidates'})"
    )


class GoogleImageProvider(ImageProvider):
    """Gemini image generation with reference-image conditioning."""

    def __init__(self, model: str | None = None) -> None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise KBError(
                "GOOGLE_API_KEY is not set — required for the 'imagen' image provider "
                "(get one at https://aistudio.google.com/apikey; see .env.example)"
            )
        self._api_key = api_key
        self._model = model or _DEFAULT_MODEL

    @property
    def model(self) -> str:
        """The Gemini model ID in use (configurable via ``KB_IMAGE_MODEL``, spec §9)."""
        return self._model

    async def _generate(
        self,
        *,
        prompt: str,
        out_path: Path,
        references: Sequence[Path],
        size: int,
    ) -> Path:
        reference_bytes = [path.read_bytes() for path in references]
        payload = build_request(prompt, reference_bytes)
        data = await self._post(payload)
        # The model returns JPEG or PNG at its native square resolution (§11.4);
        # bytes are stored as-is — image loaders sniff content, not extensions.
        atomic_write_bytes(out_path, extract_image(data))
        return out_path

    @retry(
        retry=retry_if_exception(_is_transient),
        wait=wait_random_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{_API_ROOT}/models/{self._model}:generateContent"
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                url, headers={"x-goog-api-key": self._api_key}, json=payload
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
