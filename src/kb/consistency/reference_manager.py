"""Reference-image selection for page illustrations (HC-2.2).

At most one reference per character present in the scene, never more than
``MAX_TOTAL_REFERENCES`` in total; overflow resolved by narrative-salience
order of ``Page.characters_present``.
"""

from __future__ import annotations

from kb.core.models import Book, Character, Page
from kb.image.base import MAX_TOTAL_REFERENCES


def select_references(book: Book, page: Page) -> list[Character]:
    """Characters whose primary reference accompanies this page's image request."""
    selected: list[Character] = []
    seen: set[str] = set()
    for slug in page.characters_present:
        if slug in seen:
            continue  # one reference per character, never two (HC-2.2)
        seen.add(slug)
        character = book.character(slug)
        if character is not None and character.primary_reference is not None:
            selected.append(character)
        if len(selected) == MAX_TOTAL_REFERENCES:
            break  # hard cap (HC-2.2)
    return selected
