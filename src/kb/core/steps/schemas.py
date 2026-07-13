"""Transient LLM output schemas for pipeline steps (HC-1.1).

These are what the LLM emits; persisted domain models live in ``kb.core.models``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterSpec(BaseModel):
    """One character as emitted by Step 03; the step derives the stable slug."""

    name: str
    role: str
    description: str
    visual_keywords: list[str]  # distinct per character to prevent reference bleed (HC-2.4)


class CharacterBibleSpec(BaseModel):
    """Step 03 output: the character bible."""

    characters: list[CharacterSpec]


class PageSpec(BaseModel):
    """Step 04 output for a single page."""

    text: dict[str, str]  # keyed by ISO 639-1 code (HC-1.2)
    image_prompt: str
    characters_present: list[str] = Field(
        default_factory=list
    )  # character names, narrative-salience order (consumed by HC-2.2)
