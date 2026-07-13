"""Shared fixtures: a temporary kb workspace with one universe.

An autouse fixture strips all provider credentials and kb settings from the
environment so tests can NEVER accidentally reach a real API (offline-only
policy, spec §13) — even if the developer's shell has a sourced .env.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SCRUBBED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "KB_LLM_PROVIDER",
    "KB_LLM_MODEL",
    "KB_IMAGE_PROVIDER",
    "KB_IMAGE_MODEL",
    "KB_MAX_CONCURRENCY",
    "KB_LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee zero network access and zero API cost for every test (§13)."""
    for name in _SCRUBBED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


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
