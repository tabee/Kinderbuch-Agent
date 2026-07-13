"""Step 03 — Character Bible: story → bible + one reference image per character.

Every character receives exactly one primary reference image (HC-2.1), generated
in parallel with bounded concurrency (§7.3) and persisted atomically.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from kb.consistency.prompt_builder import build_reference_prompt
from kb.core.models import Character
from kb.core.slug import slugify
from kb.core.steps.context import StepContext
from kb.core.steps.schemas import CharacterBibleSpec
from kb.core.views import write_bible_view

_SYSTEM = (
    "You are a character designer for children's picture books. "
    "Give each character DISTINCT visual keywords that cannot be confused with "
    "any other character's. Always respond via the structured output tool."
)


def is_done(ctx: StepContext) -> bool:
    book = ctx.book
    return bool(book.characters) and all(
        character.primary_reference is not None for character in book.characters
    )


def run(ctx: StepContext) -> None:
    book = ctx.book
    assert book.story is not None, "Step 02 must run before Step 03"
    beats = "\n".join(beat.narrative for beat in book.story.beats)
    prompt = (
        f"Create the character bible for the picture book '{book.title}' "
        f"(age group {book.age_group}).\n"
        f"Story:\n{beats}\n"
        "List every recurring character with role, description, and 3-5 distinct "
        "visual keywords. Keywords must be unique per character."
    )
    spec = ctx.llm.generate_structured(system=_SYSTEM, prompt=prompt, schema=CharacterBibleSpec)

    book.characters = _to_characters(spec)
    ctx.books.save(book)
    _remove_stale_references(ctx)

    asyncio.run(_generate_references(ctx))
    ctx.books.save(book)
    write_bible_view(book, ctx.book_dir)


def _to_characters(spec: CharacterBibleSpec) -> list[Character]:
    """Derive stable, unique slugs; the LLM never controls identifiers."""
    characters: list[Character] = []
    used: set[str] = set()
    for entry in spec.characters:
        slug = base = slugify(entry.name)
        suffix = 2
        while slug in used:
            slug = f"{base}-{suffix}"
            suffix += 1
        used.add(slug)
        characters.append(
            Character(
                slug=slug,
                name=entry.name,
                role=entry.role,
                description=entry.description,
                visual_keywords=entry.visual_keywords,
            )
        )
    return characters


def _remove_stale_references(ctx: StepContext) -> None:
    """Drop reference images of characters that no longer exist (HC-2.1 hygiene)."""
    references_dir = ctx.book_dir / "references"
    if not references_dir.is_dir():
        return
    current = {f"{character.slug}.png" for character in ctx.book.characters}
    for path in references_dir.glob("*.png"):
        if path.name not in current:
            path.unlink()


async def _generate_references(ctx: StepContext) -> None:
    """One reference sheet per character (HC-2.1), parallel with bounded concurrency."""
    semaphore = asyncio.Semaphore(ctx.settings.max_concurrency)

    async def generate(character: Character) -> None:
        relative = Path("references") / f"{character.slug}.png"
        prompt = build_reference_prompt(ctx.universe, character)
        async with semaphore:
            await ctx.images.generate(prompt=prompt, out_path=ctx.book_dir / relative)
        character.primary_reference = relative

    await asyncio.gather(*(generate(c) for c in ctx.book.characters))
