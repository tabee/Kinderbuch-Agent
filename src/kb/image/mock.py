"""Deterministic offline image provider for development and tests (spec §15, Phase 1).

Produces a vertical-gradient PNG whose colours derive from the prompt hash, so
identical prompts yield byte-identical files (idempotency) while different
prompts yield visibly different placeholder images.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from collections.abc import Sequence
from pathlib import Path

from kb.core.persistence import atomic_write_bytes
from kb.image.base import ImageProvider


def _gradient_png(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> bytes:
    """Minimal valid PNG of ``size`` x ``size`` pixels with a vertical gradient."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload))
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    rows = bytearray()
    for y in range(size):
        blend = y / max(size - 1, 1)
        rgb = bytes(round(t + (b - t) * blend) for t, b in zip(top, bottom, strict=True))
        rows += b"\x00" + rgb * size  # filter byte + pixels
    body = zlib.compress(bytes(rows), 9)
    signature = b"\x89PNG\r\n\x1a\n"
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", body) + chunk(b"IEND", b"")


class MockImageProvider(ImageProvider):
    """Offline stand-in for a real image model; requires no credentials."""

    async def _generate(
        self,
        *,
        prompt: str,
        out_path: Path,
        references: Sequence[Path],
        size: int,
    ) -> Path:
        digest = hashlib.sha256(prompt.encode("utf-8")).digest()
        top = (digest[0], digest[1], digest[2])
        bottom = (digest[3], digest[4], digest[5])
        atomic_write_bytes(out_path, _gradient_png(size, top, bottom))
        return out_path
