"""Image providers: abstract interface, mock implementation, and factory (HC-5.2)."""

from __future__ import annotations

from kb.config import Settings
from kb.errors import KBError
from kb.image.base import MAX_TOTAL_REFERENCES, ImageProvider
from kb.image.mock import MockImageProvider

__all__ = ["MAX_TOTAL_REFERENCES", "ImageProvider", "MockImageProvider", "create_image_provider"]


def create_image_provider(settings: Settings) -> ImageProvider:
    """Instantiate the provider selected via ``KB_IMAGE_PROVIDER`` (spec §9)."""
    if settings.image_provider == "mock":
        return MockImageProvider()
    if settings.image_provider == "imagen":
        raise KBError(
            "the 'imagen' provider arrives in Phase 4 (spec §15) — set KB_IMAGE_PROVIDER=mock"
        )
    raise KBError(
        f"unknown image provider {settings.image_provider!r} (expected 'mock' or 'imagen')"
    )
