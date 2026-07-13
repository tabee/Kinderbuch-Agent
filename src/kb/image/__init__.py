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
        from kb.image.google_image import GoogleImageProvider

        return GoogleImageProvider(model=settings.image_model)
    raise KBError(
        f"unknown image provider {settings.image_provider!r} (expected 'mock' or 'imagen')"
    )
