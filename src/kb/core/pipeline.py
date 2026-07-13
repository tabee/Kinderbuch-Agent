"""Pipeline orchestration: Steps 01-04 with idempotency and flag semantics (§7, §8.2).

Steps 01-03 run only if their artifacts are missing, or with ``--force`` when no
page-selection flags are given (page selection implies page-level work only).
Step 04 handles per-page idempotency internally.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import ModuleType

from kb.config import Settings
from kb.core.book_manager import BookManager
from kb.core.models import Book, Universe
from kb.core.steps import bible, outline, pages, story
from kb.core.steps.context import RunOptions, RunResult, StepContext
from kb.errors import KBError
from kb.image.base import ImageProvider
from kb.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_ARTIFACT_STEPS: list[tuple[str, ModuleType]] = [
    ("01 outline", outline),
    ("02 story", story),
    ("03 character bible", bible),
]


class Pipeline:
    """Runs a book through Steps 01-04. Idempotent by default (HC-4.1)."""

    def __init__(
        self,
        books: BookManager,
        universe: Universe,
        llm: LLMProvider,
        images: ImageProvider,
        settings: Settings,
        confirm: Callable[[str], bool] | None = None,
    ) -> None:
        self._books = books
        self._universe = universe
        self._llm = llm
        self._images = images
        self._settings = settings
        self._confirm = confirm

    def run(self, book: Book, options: RunOptions) -> RunResult:
        result = RunResult()
        ctx = StepContext(
            book=book,
            universe=self._universe,
            books=self._books,
            llm=self._llm,
            images=self._images,
            settings=self._settings,
            options=options,
            result=result,
        )

        force_artifacts = options.force and not options.page_restricted
        for name, step in _ARTIFACT_STEPS:
            if not force_artifacts and step.is_done(ctx):
                logger.info("step %s: up to date, skipping (HC-4.1)", name)
                continue
            self._check_confirm(f"Run step {name}?")
            logger.info("step %s: running", name)
            step.run(ctx)
            result.steps_run.append(name)

        self._check_confirm("Run step 04 pages?")
        pages.run(ctx)
        if result.pages_texted or result.pages_imaged:
            result.steps_run.append("04 pages")
        return result

    def _check_confirm(self, question: str) -> None:
        if self._confirm is not None and not self._confirm(question):
            raise KBError("run aborted by user (--interactive)")
