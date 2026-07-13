"""Generated Markdown views of structured book state (HC-1.3).

Views are derived artifacts for human review only — they are never parsed back.
"""

from __future__ import annotations

from pathlib import Path

from kb.core.models import Book
from kb.core.persistence import atomic_write_text

_HEADER = "<!-- Generated from structured state by kb; edits here are ignored (HC-1.3). -->\n\n"


def write_story_view(book: Book, book_dir: Path) -> None:
    lines = [f"# {book.title}\n"]
    if book.outline is not None:
        lines.append(f"**Premise:** {book.outline.premise}\n")
    if book.story is not None:
        for number, beat in enumerate(book.story.beats, start=1):
            lines.append(f"## Page {number}\n\n{beat.narrative}\n")
            page = next((p for p in book.pages if p.number == number), None)
            if page is not None:
                for lang, text in sorted(page.text.items()):
                    lines.append(f"**{lang}:** {text}\n")
    atomic_write_text(book_dir / "views" / "story.md", _HEADER + "\n".join(lines))


def write_bible_view(book: Book, book_dir: Path) -> None:
    lines = [f"# Character Bible — {book.title}\n"]
    for character in book.characters:
        lines.append(f"## {character.name} ({character.role})\n")
        lines.append(f"{character.description}\n")
        if character.visual_keywords:
            lines.append(f"**Visual keywords:** {', '.join(character.visual_keywords)}\n")
        if character.primary_reference is not None:
            lines.append(f"**Primary reference:** `{character.primary_reference}`\n")
    atomic_write_text(book_dir / "views" / "bible.md", _HEADER + "\n".join(lines))
