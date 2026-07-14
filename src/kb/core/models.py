"""Domain models (spec §6.1).

Page text is keyed by ISO 639-1 language code (HC-1.2). All stored paths are
relative to the book directory, so a book folder is fully portable (§6.1).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

SCHEMA_VERSION = 1

PageStatus = Literal["todo", "text_done", "image_done", "approved"]


def _check_language_codes(codes: list[str]) -> list[str]:
    for code in codes:
        if not re.fullmatch(r"[a-z]{2}", code):
            raise ValueError(f"not an ISO 639-1 language code: {code!r}")
    return codes


LanguageCodes = Annotated[list[str], AfterValidator(_check_language_codes)]


class Page(BaseModel):
    """One text/image page pair of the book (§6.2 lifecycle)."""

    number: int  # 1-based, contiguous
    text: dict[str, str] = Field(default_factory=dict)  # keyed by ISO 639-1 code (HC-1.2)
    image_prompt: str | None = None
    image_path: Path | None = None  # relative to the book directory
    characters_present: list[str] = Field(default_factory=list)  # Character.slug, salience order
    character_positions: dict[str, str] = Field(
        default_factory=dict
    )  # Character.slug → scene-true spatial phrase for HC-2.3 anchoring
    status: PageStatus = "todo"


class Character(BaseModel):
    """A story character with exactly one primary reference image (HC-2.1)."""

    slug: str  # stable kebab-case identifier
    name: str
    role: str
    description: str
    primary_reference: Path | None = None  # relative to the book directory
    visual_keywords: list[str] = Field(default_factory=list)


class Universe(BaseModel):
    """A reusable story setting from which books are created (§1.4)."""

    slug: str
    name: str
    description: str = ""
    languages: LanguageCodes
    style_guide: str = ""


class Outline(BaseModel):
    """Step 01 output: story skeleton, one synopsis per planned page (§7.1)."""

    title: str
    premise: str
    page_synopses: list[str]


class StoryBeat(BaseModel):
    """One spread's narrative; list order defines the page number (§7.1)."""

    narrative: str


class Story(BaseModel):
    """Step 02 output: the full story as ordered beats (§7.1)."""

    beats: list[StoryBeat]


class Book(BaseModel):
    """One book project; persisted under ``Books/<slug>/`` (§6.3)."""

    schema_version: int = SCHEMA_VERSION
    slug: str
    title: str
    universe_slug: str
    languages: LanguageCodes  # copied from the Universe at creation, independent afterwards
    age_group: str = "4-6"
    spreads: int = 5  # number of double-page spreads (drives Step 01)
    idea: str = ""
    outline: Outline | None = None  # Step 01 artifact
    story: Story | None = None  # Step 02 artifact
    characters: list[Character] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)

    def character(self, slug: str) -> Character | None:
        """Look up a character by its stable slug."""
        return next((c for c in self.characters if c.slug == slug), None)
