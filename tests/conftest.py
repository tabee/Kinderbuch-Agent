"""Shared fixtures: a temporary kb workspace with one universe."""

from __future__ import annotations

from pathlib import Path

import pytest

UNIVERSE_YAML = """\
slug: swiss-thai-myths
name: Swiss-Thai Myths
description: Alpine folklore meets Thai mythology.
languages: [en, th]
style_guide: Warm watercolour, soft edges, gentle light.
"""


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary working directory with ``Global/`` and ``Books/`` scaffolding."""
    universe_dir = tmp_path / "Global" / "universes" / "swiss-thai-myths"
    universe_dir.mkdir(parents=True)
    (universe_dir / "universe.yaml").write_text(UNIVERSE_YAML, encoding="utf-8")
    (tmp_path / "Books").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path
