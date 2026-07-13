"""Slug derivation for stable kebab-case identifiers (spec §6.1)."""

from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Lowercase kebab-case: ``"Anna the Bear!" -> "anna-the-bear"``."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "character"
