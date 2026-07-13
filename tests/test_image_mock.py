"""Mock image provider tests (offline, spec §13) and HC-2.2 boundary enforcement."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kb.image import MockImageProvider


def test_mock_provider_is_deterministic(tmp_path: Path) -> None:
    provider = MockImageProvider()
    first = asyncio.run(provider.generate(prompt="a bear", out_path=tmp_path / "a.png", size=64))
    second = asyncio.run(provider.generate(prompt="a bear", out_path=tmp_path / "b.png", size=64))
    other = asyncio.run(provider.generate(prompt="a fox", out_path=tmp_path / "c.png", size=64))

    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() != other.read_bytes()
    assert first.read_bytes().startswith(b"\x89PNG")


def test_hc22_reference_cap_enforced(tmp_path: Path) -> None:
    provider = MockImageProvider()
    references = [tmp_path / f"ref-{i}.png" for i in range(5)]

    with pytest.raises(ValueError, match=r"HC-2\.2"):
        asyncio.run(
            provider.generate(
                prompt="group scene",
                out_path=tmp_path / "out.png",
                references=references,
                size=64,
            )
        )


def test_four_references_allowed(tmp_path: Path) -> None:
    provider = MockImageProvider()
    references = [tmp_path / f"ref-{i}.png" for i in range(4)]

    out = asyncio.run(
        provider.generate(
            prompt="group scene", out_path=tmp_path / "out.png", references=references, size=64
        )
    )
    assert out.is_file()
