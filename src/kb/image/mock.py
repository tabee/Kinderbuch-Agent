"""Deterministic offline image provider for development and tests (spec §15, Phase 1).

Produces a solid-colour PNG whose colour is derived from the prompt hash, so
identical prompts yield byte-identical files — useful for idempotency tests.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from collections.abc import Sequence
from pathlib import Path

from kb.core.persistence import atomic_write_bytes
from kb.image.base import ImageProvider


def _solid_png(size: int, rgb: tuple[int, int, int]) -> bytes:
    """Minimal valid PNG of ``size`` x ``size`` pixels in a single colour."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload))
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    row = b"\x00" + bytes(rgb) * size  # filter byte + pixels
    body = zlib.compress(row * size, 9)
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
        atomic_write_bytes(out_path, _solid_png(size, (digest[0], digest[1], digest[2])))
        return out_path
