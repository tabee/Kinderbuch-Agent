"""Step 02 — Story: outline → structured story + Markdown view (spec §7.1, HC-1.1/1.3)."""

from __future__ import annotations

from kb.core.models import Story
from kb.core.steps.context import StepContext
from kb.core.views import write_story_view

_SYSTEM = (
    "You are an award-winning children's book author writing warm, simple prose "
    "for young children. Always respond via the structured output tool."
)


def is_done(ctx: StepContext) -> bool:
    return ctx.book.story is not None


def run(ctx: StepContext) -> None:
    book = ctx.book
    assert book.outline is not None, "Step 01 must run before Step 02"
    synopses = "\n".join(
        f"{number}. {synopsis}"
        for number, synopsis in enumerate(book.outline.page_synopses, start=1)
    )
    prompt = (
        f"Write the story for the picture book '{book.outline.title}' "
        f"(age group {book.age_group}).\n"
        f"Premise: {book.outline.premise}\n"
        f"Page synopses:\n{synopses}\n"
        "Return one story beat per synopsis, in the same order. Each beat is the "
        "narrative for one double-page spread: 2-4 short sentences."
    )
    book.story = ctx.llm.generate_structured(system=_SYSTEM, prompt=prompt, schema=Story)
    ctx.books.save(book)
    write_story_view(book, ctx.book_dir)
