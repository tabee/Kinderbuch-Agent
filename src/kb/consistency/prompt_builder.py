"""Image-prompt construction with spatial anchoring and anti-bleed measures (HC-2.3/2.4)."""

from __future__ import annotations

from kb.core.models import Character, Page, Universe

# Fallback anchors, used only when Step 04 supplied no scene-true position (HC-2.3).
_POSITIONS = (
    "on the left side of the image",
    "on the right side of the image",
    "in the center of the image",
    "in the background of the image",
)

# Image models render stray phrases as literal text; forbid it in every prompt.
_NO_TEXT = (
    "The image must contain no written text of any kind: no words, letters, "
    "numbers, captions, labels, speech bubbles, signs, signatures, or watermarks."
)

# Manga/print styles provoke frames, page margins and panel layouts — print
# pages are full-bleed (HC-3.2), so every prompt forbids them explicitly.
_FULL_BLEED = (
    "Full-bleed artwork: the picture fills the ENTIRE square canvas edge to edge. "
    "No borders, no frames, no white or black margins, no letterboxing, no "
    "vignette edges, no panel layout, no visible canvas or paper around the artwork."
)


def build_reference_prompt(universe: Universe, character: Character) -> str:
    """Prompt for a character's primary reference image (spec §7.2).

    Deliberately *not* worded as a "model sheet": sheet-style requests provoke
    annotated multi-view layouts whose labels then bleed into page images.
    """
    keywords = ", ".join(character.visual_keywords)
    return (
        f"A single full-body illustration of {character.name} ({character.role}): "
        "exactly one figure, full body from head to feet, neutral standing pose, "
        "facing the viewer, no scene props, no other characters, on a plain light "
        "background that extends to every edge of the image. "
        f"{character.description} "
        f"Distinct visual features: {keywords}. "
        f"{_FULL_BLEED} "
        f"{_NO_TEXT} "
        f"Illustration style: {universe.style_guide}"
    )


def build_page_image_prompt(universe: Universe, page: Page, references: list[Character]) -> str:
    """Page-illustration prompt binding each reference image to a named character.

    Every reference is anchored to a name and a position (HC-2.3) — preferring
    the scene-true position captured in Step 04 over generic fallbacks — with
    distinct visual keywords per character to prevent identity mixing (HC-2.4).
    The scene leads and the references are explicitly identity-only, so the
    result is a story illustration, never a character sheet.
    """
    lines = [
        "A storybook page illustration: exactly one single coherent scene — not a "
        "character sheet, not a lineup, not a collage; never divide the image into "
        "panels.",
        _FULL_BLEED,
        f"Scene: {page.image_prompt or 'A gentle storybook scene.'}",
    ]
    if references:
        lines.append(
            "The attached reference images define each character's IDENTITY only "
            "(face, colours, clothing, proportions). Do not copy their neutral pose, "
            "plain background, or composition — every character acts naturally within "
            "the scene described above."
        )
    for index, character in enumerate(references, start=1):
        position = (
            page.character_positions.get(character.slug)
            or _POSITIONS[(index - 1) % len(_POSITIONS)]
        )
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
    lines.append(_NO_TEXT)
    lines.append(f"Illustration style: {universe.style_guide}")
    return "\n".join(lines)
