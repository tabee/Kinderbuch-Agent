"""Edit operations with the exact lifecycle semantics of spec §6.2."""

from __future__ import annotations

import asyncio
from pathlib import Path

from kb.consistency.prompt_builder import build_page_image_prompt
from kb.consistency.reference_manager import select_references
from kb.core.book_manager import BookManager
from kb.core.models import Book, Character, Outline, Page, Story, Universe
from kb.core.slug import slugify
from kb.core.steps.prose import prose_guidance
from kb.core.steps.schemas import (
    BookConceptSpec,
    CharacterBibleSpec,
    ImagePromptSpec,
    PageTextSpec,
    UniverseRevisionSpec,
)
from kb.core.universe_manager import UniverseManager
from kb.core.views import write_bible_view, write_story_view
from kb.errors import KBError
from kb.image.base import ImageProvider
from kb.llm.base import LLMProvider


def edit_universe(
    universes: UniverseManager, universe: Universe, llm: LLMProvider, instruction: str
) -> Universe:
    """Revise universe settings while preserving its stable slug."""
    prompt = (
        f"Revise the reusable story universe '{universe.name}'.\n"
        f"Description: {universe.description}\n"
        f"Languages: {', '.join(universe.languages)}\n"
        f"Illustration style: {universe.style_guide}\n"
        f"Instruction: {instruction}\n"
        "Return the complete revised universe. Languages must be ISO 639-1 codes."
    )
    spec = llm.generate_structured(
        system="You design reusable children's-book universes. Always use structured output.",
        prompt=prompt,
        schema=UniverseRevisionSpec,
    )
    revised = Universe(slug=universe.slug, **spec.model_dump())
    universes.save(revised)
    return revised


def replace_book_concept(books: BookManager, book: Book, concept: BookConceptSpec) -> Book:
    """Replace the creative brief and invalidate all generated artifacts."""
    book.title = concept.title
    book.idea = concept.idea
    book.age_group = concept.age_group
    book.spreads = concept.spreads
    book.outline = None
    book.story = None
    book.characters = []
    book.pages = []
    books.clear_generated_artifacts(book.slug)
    books.save(book)
    return book


def edit_book_concept(books: BookManager, book: Book, llm: LLMProvider, instruction: str) -> Book:
    """Revise the book's creative brief through structured output (HC-1.1)."""
    prompt = (
        f"Revise this book concept.\nTitle: {book.title}\nIdea: {book.idea}\n"
        f"Age group: {book.age_group}\nSpreads: {book.spreads}\n"
        f"Instruction: {instruction}\nReturn the complete revised concept."
    )
    concept = llm.generate_structured(
        system="You develop children's-book concepts. Always use structured output.",
        prompt=prompt,
        schema=BookConceptSpec,
    )
    return replace_book_concept(books, book, concept)


def replace_outline(books: BookManager, book: Book, outline: Outline) -> Outline:
    """Replace the outline and invalidate every downstream artifact."""
    if len(outline.page_synopses) != book.spreads:
        raise KBError(
            f"revised outline has {len(outline.page_synopses)} page synopses; "
            f"expected {book.spreads}"
        )
    book.outline = outline
    book.title = outline.title
    book.story = None
    book.characters = []
    book.pages = []
    books.clear_generated_artifacts(book.slug)
    books.save(book)
    return outline


def replace_story(books: BookManager, book: Book, story: Story) -> Story:
    """Replace the story and invalidate its bible and pages."""
    if len(story.beats) != book.spreads:
        raise KBError(f"revised story has {len(story.beats)} beats; expected {book.spreads}")
    book.story = story
    book.characters = []
    book.pages = []
    books.clear_generated_artifacts(book.slug)
    books.save(book)
    write_story_view(book, books.book_dir(book.slug))
    return story


def edit_outline(books: BookManager, book: Book, llm: LLMProvider, instruction: str) -> Outline:
    """Revise the complete outline through structured LLM output (HC-1.1)."""
    if book.outline is None:
        raise KBError("the book has no outline yet — run Step 01 first")
    current = "\n".join(
        f"{number}. {synopsis}"
        for number, synopsis in enumerate(book.outline.page_synopses, start=1)
    )
    prompt = (
        f"Revise the outline for the book '{book.title}' (age group {book.age_group}).\n"
        f"Current title: {book.outline.title}\n"
        f"Current premise: {book.outline.premise}\n"
        f"Current page synopses:\n{current}\n"
        f"Instruction: {instruction}\n"
        f"Return the complete revised outline with exactly {book.spreads} page synopses."
    )
    revised = llm.generate_structured(
        system="You revise children's-book outlines. Always respond via structured output.",
        prompt=prompt,
        schema=Outline,
    )
    return replace_outline(books, book, revised)


def edit_story(books: BookManager, book: Book, llm: LLMProvider, instruction: str) -> Story:
    """Revise the complete story through structured LLM output (HC-1.1)."""
    if book.story is None:
        raise KBError("the book has no story yet — run Step 02 first")
    current = "\n".join(
        f"{number}. {beat.narrative}" for number, beat in enumerate(book.story.beats, start=1)
    )
    prompt = (
        f"Revise the story for the book '{book.title}' (age group {book.age_group}).\n"
        f"Current story beats:\n{current}\n"
        f"Instruction: {instruction}\n"
        f"Return the complete revised story with exactly {book.spreads} beats. "
        f"{prose_guidance(book.age_group)}"
    )
    revised = llm.generate_structured(
        system="You revise children's-book stories. Always respond via structured output.",
        prompt=prompt,
        schema=Story,
    )
    return replace_story(books, book, revised)


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


def rewrite_text(
    books: BookManager, book: Book, llm: LLMProvider, number: int, instruction: str
) -> Page:
    """LLM-assisted rewrite of a page's text in every configured language (§6.2)."""
    page = get_page(book, number)
    if not page.text:
        raise KBError(f"page {number} has no text yet — run the pipeline first")
    current = "\n".join(f"[{lang}] {text}" for lang, text in sorted(page.text.items()))
    languages = ", ".join(book.languages)
    prompt = (
        f"Revise the text of page {page.number} of the illustrated book '{book.title}' "
        f"(age group {book.age_group}).\n"
        f"Current text:\n{current}\n"
        f"Instruction: {instruction}\n"
        f"Return the complete revised text in these languages (ISO 639-1 keys): {languages}. "
        f"All languages must express the same content. {prose_guidance(book.age_group)}"
    )
    spec = llm.generate_structured(
        system="You are an award-winning author revising bilingual page text. "
        "Always respond via the structured output tool.",
        prompt=prompt,
        schema=PageTextSpec,
    )
    missing = set(book.languages) - set(spec.text)
    if missing:
        raise KBError(f"page {number}: LLM omitted language(s) {sorted(missing)} (HC-1.2)")
    return edit_text(books, book, number, {lang: spec.text[lang] for lang in book.languages})


def rewrite_image_prompt(
    books: BookManager,
    book: Book,
    universe: Universe,
    llm: LLMProvider,
    images: ImageProvider,
    number: int,
    instruction: str,
) -> Page:
    """Have the LLM revise an image prompt, then regenerate the image."""
    page = get_page(book, number)
    if page.image_prompt is None:
        raise KBError(f"page {number} has no image prompt yet — run the pipeline first")
    prompt = (
        f"Revise this illustration prompt for page {number} of '{book.title}'.\n"
        f"Current prompt: {page.image_prompt}\nInstruction: {instruction}\n"
        "Return one complete replacement prompt. It must describe one coherent scene and no text."
    )
    revised = llm.generate_structured(
        system="You revise storybook illustration prompts. Always use structured output.",
        prompt=prompt,
        schema=ImagePromptSpec,
    )
    return edit_image(books, book, universe, images, number, revised.image_prompt, replace=True)


def edit_image(
    books: BookManager,
    book: Book,
    universe: Universe,
    images: ImageProvider,
    number: int,
    instruction: str,
    replace: bool = False,
) -> Page:
    """Regenerate the image (§6.2).

    By default the instruction is appended to the original prompt; with
    ``replace=True`` it becomes the new prompt — the escape hatch when the
    original scene keeps triggering the provider's content-safety filter.
    """
    page = get_page(book, number)
    if replace:
        page.image_prompt = instruction
    else:
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
