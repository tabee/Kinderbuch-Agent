"""Slug derivation for stable kebab-case identifiers (spec §6.1)."""

from __future__ import annotations

import re
import unicodedata

from kb.errors import KBError

_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def slugify(text: str) -> str:
    """ASCII kebab-case: ``"Leo Zürcher!" -> "leo-zurcher"``."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "character"


def validate_slug(value: str) -> str:
    """Check a user-supplied identifier is kebab-case; shared by CLI, assistant, web UI."""
    if not _SLUG_RE.fullmatch(value):
        raise KBError(f"slug must be kebab-case ([a-z0-9-]), got {value!r}")
    return value
