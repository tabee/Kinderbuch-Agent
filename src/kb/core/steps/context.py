"""Shared pipeline-run context and options (spec §8.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kb.config import Settings
from kb.core.book_manager import BookManager
from kb.core.models import Book, Page, Universe
from kb.image.base import ImageProvider
from kb.llm.base import LLMProvider


@dataclass(frozen=True)
class RunOptions:
    """CLI flag values with the exact semantics of spec §8.2 (HC-4.2)."""

    force: bool = False
    recreate_images: bool = False
    from_page: int | None = None
    pages: set[int] | None = None
    interactive: bool = False

    @property
    def page_restricted(self) -> bool:
        return self.from_page is not None or self.pages is not None

    def selects(self, page: Page) -> bool:
        """Page-selection flags combine by intersection (§8.2)."""
        if self.from_page is not None and page.number < self.from_page:
            return False
        return self.pages is None or page.number in self.pages


@dataclass
class RunResult:
    """Summary of one pipeline run (reported by the CLI, §7.3)."""

    steps_run: list[str] = field(default_factory=list)
    pages_texted: int = 0
    pages_imaged: int = 0
    failed_pages: dict[int, str] = field(default_factory=dict)


@dataclass
class StepContext:
    """Everything a pipeline step needs; providers are injected (HC-5.2)."""

    book: Book
    universe: Universe
    books: BookManager
    llm: LLMProvider
    images: ImageProvider
    settings: Settings
    options: RunOptions
    result: RunResult

    @property
    def book_dir(self) -> Path:
        return self.books.book_dir(self.book.slug)
