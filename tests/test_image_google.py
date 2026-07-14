"""Google image provider tests — offline only; the network path is never exercised (Gate 4)."""

from __future__ import annotations

import base64

import httpx
import pytest

from kb.config import Settings
from kb.errors import ImageSafetyError, KBError
from kb.image import create_image_provider
from kb.image.google_image import (
    GoogleImageProvider,
    _is_transient,
    build_request,
    extract_image,
)

PNG = b"\x89PNG\r\n\x1a\nfakepng"
JPEG = b"\xff\xd8\xfffakejpeg"


@pytest.fixture
def google_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-no-network")


def test_hc53_fails_fast_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(KBError, match="GOOGLE_API_KEY"):
        GoogleImageProvider()


def test_factory_selects_google_provider(google_key: None) -> None:
    provider = create_image_provider(Settings(image_provider="imagen"))
    assert isinstance(provider, GoogleImageProvider)
    assert provider.model == "gemini-3.1-flash-image"


def test_kb_image_model_overrides_default(
    google_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KB_IMAGE_PROVIDER", "imagen")
    monkeypatch.setenv("KB_IMAGE_MODEL", "gemini-3-pro-image")
    provider = create_image_provider(Settings.from_env())
    assert isinstance(provider, GoogleImageProvider)
    assert provider.model == "gemini-3-pro-image"


def test_hc23_reference_parts_precede_prompt_in_salience_order() -> None:
    payload = build_request("Anna, matching reference image 1 ...", [PNG, JPEG])

    parts = payload["contents"][0]["parts"]
    assert len(parts) == 3
    assert base64.b64decode(parts[0]["inlineData"]["data"]) == PNG
    assert parts[0]["inlineData"]["mimeType"] == "image/png"
    assert base64.b64decode(parts[1]["inlineData"]["data"]) == JPEG
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert parts[2] == {"text": "Anna, matching reference image 1 ..."}
    assert payload["generationConfig"]["imageConfig"]["aspectRatio"] == "1:1"


def test_extract_image_happy_path() -> None:
    encoded = base64.b64encode(JPEG).decode()
    data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "here you go"},
                        {"inlineData": {"mimeType": "image/jpeg", "data": encoded}},
                    ]
                }
            }
        ]
    }
    assert extract_image(data) == JPEG


def test_extract_image_without_image_raises() -> None:
    with pytest.raises(KBError, match="no image data"):
        extract_image({"candidates": [{"content": {"parts": [{"text": "hm"}]}}]})
    with pytest.raises(KBError, match="no candidates"):
        extract_image({})


@pytest.mark.parametrize("reason", ["SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT"])
def test_safety_refusal_raises_dedicated_actionable_error(reason: str) -> None:
    """Safety blocks are permanent — the error must say so and point at kb edit --image."""
    refusal = {"candidates": [{"content": {"parts": [{"text": "sorry"}]}, "finishReason": reason}]}
    with pytest.raises(ImageSafetyError) as excinfo:
        extract_image(refusal)
    message = str(excinfo.value)
    assert reason in message
    assert "Retrying will not help" in message
    assert "kb edit" in message and "--image" in message


def test_prompt_level_block_reason_raises_safety_error() -> None:
    """Input-level blocks arrive as promptFeedback.blockReason without candidates."""
    with pytest.raises(ImageSafetyError):
        extract_image({"promptFeedback": {"blockReason": "SAFETY"}})


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, True), (500, True), (503, True), (400, False), (401, False), (404, False)],
)
def test_retry_policy_classification(status: int, expected: bool) -> None:
    """§10: retry only transient failures; never auth/validation errors."""
    request = httpx.Request("POST", "https://example.invalid")
    exc = httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(status, request=request)
    )
    assert _is_transient(exc) is expected


def test_network_errors_are_transient() -> None:
    assert _is_transient(httpx.ConnectError("down")) is True
    assert _is_transient(ValueError("nope")) is False
