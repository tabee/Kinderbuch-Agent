"""Edit operations with the exact lifecycle semantics of spec §6.2."""

from __future__ import annotations

import asyncio
from pathlib import Path

from kb.consistency.prompt_builder import build_page_image_prompt
from kb.consistency.reference_manager import select_references
from kb.core.book_manager import BookManager
from kb.core.models import Book, Character, Page, Universe
from kb.core.slug import slugify
from kb.core.steps.schemas import CharacterBibleSpec
from kb.core.views import write_bible_view, write_story_view
from kb.errors import KBError
from kb.image.base import ImageProvider
from kb.llm.base import LLMProvider


def get_page(book: Book, number: int) -> Page:
    page = next((p for p in book.pages if p.number == number), None)
    if page is None:
        raise KBError(f"book {book.slug!r} has no page {number}")
    return page


def edit_text(books: BookManager, book: Book, number: int, texts: dict[str, str]) -> Page:
    """Update text and revoke approval; status per §6.2."""
    page = get_page(book, number)
    page.text.update(texts)
    page.status = "image_done" if page.image_path is not None else "text_done"
    books.save_page(book.slug, page)
    write_story_view(book, books.book_dir(book.slug))
    return page


def edit_image(
    books: BookManager,
    book: Book,
    universe: Universe,
    images: ImageProvider,
    number: int,
    instruction: str,
) -> Page:
    """Regenerate the image with the instruction appended to the original prompt (§6.2)."""
    page = get_page(book, number)
    if page.image_prompt is None:
        raise KBError(f"page {number} has no image prompt yet — run the pipeline first")
    page.image_prompt = f"{page.image_prompt}\nEdit: {instruction}"

    references = select_references(book, page)  # HC-2.2
    prompt = build_page_image_prompt(universe, page, references)  # HC-2.3/2.4
    book_dir = books.book_dir(book.slug)
    reference_paths = [
        book_dir / c.primary_reference for c in references if c.primary_reference is not None
    ]
    relative = page.image_path or Path("images") / f"page-{page.number:03d}.png"
    asyncio.run(
        images.generate(prompt=prompt, out_path=book_dir / relative, references=reference_paths)
    )
    page.image_path = relative
    page.status = "image_done"  # approval revoked (§6.2)
    books.save_page(book.slug, page)
    return page


def edit_bible(
    books: BookManager, book: Book, llm: LLMProvider, instruction: str
) -> list[Character]:
    """Revise the character bible per instruction; existing reference images are kept
    for characters whose slug is unchanged (use ``kb run --recreate-images`` to redraw).
    """
    current = "\n".join(
        f"- {c.name} ({c.role}): {c.description} [keywords: {', '.join(c.visual_keywords)}]"
        for c in book.characters
    )
    prompt = (
        f"Revise the character bible for the picture book '{book.title}'.\n"
        f"Current bible:\n{current or '(empty)'}\n"
        f"Instruction: {instruction}\n"
        "Return the COMPLETE revised bible with distinct visual keywords per character."
    )
    spec = llm.generate_structured(
        system="You are a character designer for children's picture books. "
        "Always respond via the structured output tool.",
        prompt=prompt,
        schema=CharacterBibleSpec,
    )

    existing = {c.slug: c for c in book.characters}
    revised: list[Character] = []
    used: set[str] = set()
    for entry in spec.characters:
        slug = base = slugify(entry.name)
        suffix = 2
        while slug in used:
            slug = f"{base}-{suffix}"
            suffix += 1
        used.add(slug)
        previous = existing.get(slug)
        revised.append(
            Character(
                slug=slug,
                name=entry.name,
                role=entry.role,
                description=entry.description,
                visual_keywords=entry.visual_keywords,
                primary_reference=previous.primary_reference if previous else None,
            )
        )
    book.characters = revised
    books.save(book)
    write_bible_view(book, books.book_dir(book.slug))
    return revised


def approve_page(books: BookManager, book: Book, number: int) -> Page:
    """Transition ``image_done -> approved`` only; anything else is an error (§6.2)."""
    page = get_page(book, number)
    if page.status != "image_done":
        raise KBError(
            f"page {number} is {page.status!r} — only 'image_done' pages can be approved (§6.2)"
        )
    page.status = "approved"
    books.save_page(book.slug, page)
    return page
