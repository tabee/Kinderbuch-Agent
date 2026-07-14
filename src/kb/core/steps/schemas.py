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
    visual_keywords: list[str] = Field(
        description=(
            "3-5 concrete, paintable features unique to this character — colours, "
            "clothing, body shape, accessories (e.g. 'ragged red scarf', 'ash-grey "
            "fur'). Never sounds, smells, emotions, story events, or poetic phrases: "
            "they cannot be drawn and end up rendered as text in the image."
        )
    )  # distinct per character to prevent reference bleed (HC-2.4)


class CharacterBibleSpec(BaseModel):
    """Step 03 output: the character bible."""

    characters: list[CharacterSpec]


class PageSpec(BaseModel):
    """Step 04 output for a single page."""

    text: dict[str, str]  # keyed by ISO 639-1 code (HC-1.2)
    image_prompt: str = Field(
        description=(
            "Illustration prompt for ONE coherent story moment: setting, lighting, "
            "mood, and each present character's action and place in the scene. "
            "Purely visual — the illustration itself must never contain written words."
        )
    )
    characters_present: list[str] = Field(
        default_factory=list
    )  # character names, narrative-salience order (consumed by HC-2.2)
    character_positions: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "For each name in characters_present, a short spatial phrase locating the "
            "character in this scene, e.g. 'kneeling in the mud, centre foreground'."
        ),
    )  # feeds HC-2.3 spatial anchoring with scene-true positions


class PageTextSpec(BaseModel):
    """LLM-assisted text rewrite (``kb edit --text``): text only, image untouched."""

    text: dict[str, str]  # keyed by ISO 639-1 code (HC-1.2)
