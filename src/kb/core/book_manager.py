"""Book state management with atomic YAML persistence (spec §6.3, HC-4.3/4.4)."""

from __future__ import annotations

from pathlib import Path

from kb.core.models import SCHEMA_VERSION, Book, Page, Universe
from kb.core.persistence import atomic_write_yaml, read_yaml
from kb.errors import KBError, NotFoundError


class BookManager:
    """Creates, loads, and saves books under a ``Books/`` directory."""

    def __init__(self, books_dir: Path) -> None:
        self._books_dir = books_dir

    def book_dir(self, slug: str) -> Path:
        return self._books_dir / slug

    def exists(self, slug: str) -> bool:
        return (self.book_dir(slug) / "book.yaml").is_file()

    def list_slugs(self) -> list[str]:
        if not self._books_dir.is_dir():
            return []
        return sorted(p.name for p in self._books_dir.iterdir() if (p / "book.yaml").is_file())

    def create(
        self,
        slug: str,
        universe: Universe,
        *,
        languages: list[str] | None = None,
        age_group: str = "4-6",
        idea: str = "",
        spreads: int = 5,
    ) -> Book:
        """Create a book; languages are copied from the universe unless overridden (§6.1)."""
        book = Book(
            slug=slug,
            title=slug.replace("-", " ").title(),
            universe_slug=universe.slug,
            languages=list(languages if languages is not None else universe.languages),
            age_group=age_group,
            idea=idea,
            spreads=spreads,
        )
        self.save(book)
        return book

    def save(self, book: Book) -> None:
        """Persist ``book.yaml`` (without pages) plus one file per page, atomically."""
        book_dir = self.book_dir(book.slug)
        (book_dir / "pages").mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(book_dir / "book.yaml", book.model_dump(mode="json", exclude={"pages"}))
        for page in book.pages:
            self.save_page(book.slug, page)

    def save_page(self, slug: str, page: Page) -> None:
        """Persist a single page immediately (resumability, §7.3)."""
        pages_dir = self.book_dir(slug) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(pages_dir / f"{page.number:03d}.yaml", page.model_dump(mode="json"))

    def load(self, slug: str) -> Book:
        book_file = self.book_dir(slug) / "book.yaml"
        if not book_file.is_file():
            raise NotFoundError(f"unknown book: {slug!r}")
        data = read_yaml(book_file)
        version = int(data.get("schema_version", 1))
        if version > SCHEMA_VERSION:
            raise KBError(
                f"book {slug!r} has schema_version {version}, but this build supports "
                f"<= {SCHEMA_VERSION} — upgrade kb (§6.1)"
            )
        pages_dir = self.book_dir(slug) / "pages"
        pages = (
            [read_yaml(f) for f in sorted(pages_dir.glob("*.yaml"))] if pages_dir.is_dir() else []
        )
        return Book.model_validate({**data, "pages": pages})
