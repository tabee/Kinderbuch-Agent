"""Step 04 — Pages: structured per-page text + parallel image generation.

Text: one structured LLM call per page (HC-1.1/1.2), persisted immediately.
Images: `asyncio.gather` behind a bounded semaphore with per-page failure
isolation (§7.3). Idempotent by default; flag semantics per §8.2.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from kb.consistency.prompt_builder import build_page_image_prompt
from kb.consistency.reference_manager import select_references
from kb.core.models import Book, Character, Page
from kb.core.steps.context import StepContext
from kb.core.steps.prose import prose_guidance
from kb.core.steps.schemas import PageSpec
from kb.core.views import write_story_view
from kb.errors import ImageSafetyError, KBError

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You write bilingual picture-book page text and illustration prompts. "
    "Provide the page text in EVERY requested language. "
    "List characters_present in order of narrative importance. "
    "Illustration prompts describe ONE coherent scene moment — setting, lighting, "
    "atmosphere, and each character's action — and are purely visual: the "
    "illustration must never contain written words. "
    "Always respond via the structured output tool."
)


def run(ctx: StepContext) -> None:
    book = ctx.book
    assert book.story is not None, "Step 02 must run before Step 04"

    if not book.pages:
        book.pages = [Page(number=number) for number in range(1, len(book.story.beats) + 1)]
        ctx.books.save(book)

    selected = [page for page in book.pages if ctx.options.selects(page)]

    for page in selected:
        if _needs_text(page, ctx):
            _generate_text(ctx, page)

    to_image = [page for page in selected if _needs_image(page, ctx)]
    if to_image:
        asyncio.run(_generate_images(ctx, to_image))

    write_story_view(book, ctx.book_dir)

    if ctx.result.failed_pages:
        raise KBError(_failure_summary(ctx))


def _failure_summary(ctx: StepContext) -> str:
    """Actionable failure report: retryable pages vs. permanent safety refusals."""
    failed = sorted(ctx.result.failed_pages)
    safety = sorted(ctx.result.safety_blocked)
    retryable = [n for n in failed if n not in ctx.result.safety_blocked]
    parts = [f"image generation failed for page(s) {', '.join(str(n) for n in failed)}"]
    if retryable:
        parts.append(f"page(s) {', '.join(str(n) for n in retryable)}: re-run to retry (§7.3)")
    if safety:
        parts.append(
            f"page(s) {', '.join(str(n) for n in safety)}: REFUSED by the image "
            "provider's content-safety filter — retrying will not help; soften the "
            f"scene instead, e.g.: kb edit {ctx.book.slug} --page {safety[0]} --image "
            '"symbolic and dreamlike, no gore, no graphic violence" (still refused? '
            f"replace the prompt: kb edit {ctx.book.slug} --page {safety[0]} "
            '--image-prompt "<new calmer scene>")'
        )
    return "; ".join(parts)


def _needs_text(page: Page, ctx: StepContext) -> bool:
    if ctx.options.force:
        return True  # --force regenerates everything selected, including approved (§8.2)
    if ctx.options.recreate_images:
        return False  # --recreate-images keeps texts (§8.2)
    return page.status == "todo"  # default: idempotent (HC-4.1)


def _needs_image(page: Page, ctx: StepContext) -> bool:
    if page.status == "todo":
        return False  # no text yet (e.g. its text generation just failed)
    if ctx.options.force or ctx.options.recreate_images:
        return True  # approval is revoked by regeneration (§8.2)
    return page.status == "text_done"


def _generate_text(ctx: StepContext, page: Page) -> None:
    book = ctx.book
    assert book.story is not None
    beat = book.story.beats[page.number - 1].narrative
    characters = ", ".join(f"{c.name}" for c in book.characters) or "none defined"
    languages = ", ".join(book.languages)
    prompt = (
        f"Write page {page.number} of the illustrated book '{book.title}' "
        f"(age group {book.age_group}).\n"
        f"Narrative for this page: {beat}\n"
        f"Known characters: {characters}\n"
        f"Provide the page text in these languages (ISO 639-1 keys): {languages}. "
        f"{prose_guidance(book.age_group)}\n"
        "Also provide an illustration prompt for the facing image page — one "
        "coherent scene moment with setting, lighting, mood, and each character's "
        "action; no written words in the illustration — plus the characters "
        "present (most important first) and character_positions placing each "
        "present character within this scene."
    )
    spec = ctx.llm.generate_structured(system=_SYSTEM, prompt=prompt, schema=PageSpec)

    missing = set(book.languages) - set(spec.text)
    if missing:
        raise KBError(f"page {page.number}: LLM omitted language(s) {sorted(missing)} (HC-1.2)")

    page.text = {lang: spec.text[lang] for lang in book.languages}
    page.image_prompt = spec.image_prompt
    page.characters_present = _names_to_slugs(spec.characters_present, book)
    page.character_positions = _positions_to_slugs(spec.character_positions, book)
    page.status = "text_done"  # any previous image/approval is superseded (§6.2)
    ctx.books.save_page(book.slug, page)
    ctx.result.pages_texted += 1


def _names_to_slugs(names: list[str], book: Book) -> list[str]:
    """Map LLM-reported character names to stable slugs, preserving salience order."""
    slugs: list[str] = []
    for name in names:
        character = _find_character(name, book)
        if character is None:
            logger.debug("dropping unknown character reference %r", name)
        elif character.slug not in slugs:
            slugs.append(character.slug)
    return slugs


def _positions_to_slugs(positions: dict[str, str], book: Book) -> dict[str, str]:
    """Re-key LLM-reported scene positions by stable character slug (HC-2.3)."""
    result: dict[str, str] = {}
    for name, position in positions.items():
        character = _find_character(name, book)
        if character is not None and position.strip():
            result[character.slug] = position.strip()
    return result


def _find_character(name: str, book: Book) -> Character | None:
    needle = name.casefold()
    return next(
        (c for c in book.characters if c.name.casefold() == needle or c.slug == needle),
        None,
    )


async def _generate_images(ctx: StepContext, pages: list[Page]) -> None:
    """Parallel, failure-isolated image generation (§7.3)."""
    semaphore = asyncio.Semaphore(ctx.settings.max_concurrency)

    async def generate(page: Page) -> None:
        references = select_references(ctx.book, page)  # HC-2.2
        prompt = build_page_image_prompt(ctx.universe, page, references)  # HC-2.3/2.4
        relative = Path("images") / f"page-{page.number:03d}.png"
        reference_paths = [
            ctx.book_dir / c.primary_reference
            for c in references
            if c.primary_reference is not None
        ]
        async with semaphore:
            await ctx.images.generate(
                prompt=prompt, out_path=ctx.book_dir / relative, references=reference_paths
            )
        page.image_prompt = prompt if page.image_prompt is None else page.image_prompt
        page.image_path = relative
        page.status = "image_done"
        ctx.books.save_page(ctx.book.slug, page)  # persist immediately → resumable
        ctx.result.pages_imaged += 1

    outcomes = await asyncio.gather(*(generate(p) for p in pages), return_exceptions=True)
    for page, outcome in zip(pages, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            logger.warning("page %d image failed: %s", page.number, outcome)
            ctx.result.failed_pages[page.number] = str(outcome)
            if isinstance(outcome, ImageSafetyError):
                ctx.result.safety_blocked.add(page.number)
