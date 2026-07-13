"""Age-appropriate prose guidance for the writing steps (01, 02, 04)."""

from __future__ import annotations

import re


def prose_guidance(age_group: str) -> str:
    """Reading-level instructions derived from the lower bound of the age group."""
    match = re.search(r"\d+", age_group)
    age = int(match.group()) if match else 5
    if age >= 12:
        return (
            "Write for young adults: rich, layered prose with 5-8 sentences per page "
            "(at most 120 words per language), authentic dialogue, emotional nuance, "
            "and room for conflict and ambiguity. Do not talk down to the reader."
        )
    if age >= 7:
        return (
            "Write for middle-grade readers: 4-6 sentences per page, vivid but clear "
            "language, gentle tension that resolves."
        )
    return (
        "Write for pre-readers being read to: 2-4 short, rhythmic sentences per page, "
        "simple warm language, nothing scary."
    )
