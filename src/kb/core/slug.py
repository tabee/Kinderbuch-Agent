"""Slug derivation for stable kebab-case identifiers (spec §6.1)."""

from __future__ import annotations

import re
import unicodedata


def slugify(text: str) -> str:
    """ASCII kebab-case: ``"Leo Zürcher!" -> "leo-zurcher"``."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "character"
