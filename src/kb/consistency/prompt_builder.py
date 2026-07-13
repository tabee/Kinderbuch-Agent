"""Image-prompt construction with spatial anchoring and anti-bleed measures (HC-2.3/2.4)."""

from __future__ import annotations

from kb.core.models import Character, Page, Universe

_POSITIONS = (
    "on the left side of the image",
    "on the right side of the image",
    "in the center of the image",
    "in the background of the image",
)


def build_reference_prompt(universe: Universe, character: Character) -> str:
    """Prompt for a character's primary reference sheet (spec §7.2)."""
    keywords = ", ".join(character.visual_keywords)
    return (
        f"Character reference sheet for {character.name} ({character.role}): "
        "full body, neutral standing pose, plain light background, no scene props. "
        f"{character.description} "
        f"Distinct visual features: {keywords}. "
        f"Illustration style: {universe.style_guide}"
    )


def build_page_image_prompt(universe: Universe, page: Page, references: list[Character]) -> str:
    """Page-illustration prompt binding each reference image to a named character.

    Every reference is anchored to a name and a position (HC-2.3), with distinct
    visual keywords per character to prevent identity mixing (HC-2.4).
    """
    lines = [page.image_prompt or "A gentle storybook scene."]
    for index, character in enumerate(references, start=1):
        position = _POSITIONS[(index - 1) % len(_POSITIONS)]
        keywords = ", ".join(character.visual_keywords)
        lines.append(
            f"{character.name}, matching reference image {index}, is {position}. "
            f"Distinct visual features of {character.name}: {keywords}."
        )
    if references:
        lines.append(
            "Each reference image corresponds only to its named character; "
            "do not blend or mix character identities."
        )
    lines.append(f"Illustration style: {universe.style_guide}")
    return "\n".join(lines)
