"""Step 01 — Outline: idea + universe context → structured outline (spec §7.1, HC-1.1)."""

from __future__ import annotations

from kb.core.models import Outline
from kb.core.steps.context import StepContext

_SYSTEM = (
    "You are an award-winning children's book author. "
    "You plan gentle, age-appropriate picture books. "
    "Always respond via the structured output tool."
)


def is_done(ctx: StepContext) -> bool:
    return ctx.book.outline is not None


def run(ctx: StepContext) -> None:
    book, universe = ctx.book, ctx.universe
    idea = book.idea or f"A story called '{book.title}'."
    prompt = (
        f"Create the outline for an illustrated children's/young readers' book "
        f"(age group {book.age_group}).\n"
        f"Idea: {idea}\n"
        f"Universe: {universe.name} — {universe.description}\n"
        f"The book has {book.spreads} double-page spreads; provide exactly one short "
        "synopsis per spread in page_synopses, in reading order. "
        "Give the book its own evocative title — never reuse the universe name."
    )
    book.outline = ctx.llm.generate_structured(system=_SYSTEM, prompt=prompt, schema=Outline)
    if book.title == _default_title(book.slug):
        book.title = book.outline.title  # adopt the authored title unless the user set one
    ctx.books.save(book)


def _default_title(slug: str) -> str:
    return slug.replace("-", " ").title()
