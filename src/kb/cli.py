"""Command-line interface for kb (spec §8).

Exit codes (§8.3): 0 success, 1 runtime failure, 2 usage error. Unknown
books/universes and invalid ``--pages`` specs are usage errors; pipeline
functionality not yet implemented in the current phase exits 1.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from kb import __version__
from kb.config import Settings
from kb.core.book_manager import BookManager
from kb.core.models import Book, Universe
from kb.core.pagespec import parse_page_spec
from kb.core.universe_manager import UniverseManager
from kb.errors import KBError, NotFoundError
from kb.logging_setup import setup_logging

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="kb — bilingual illustrated children's books, from idea to print-ready PDF.",
)
universe_app = typer.Typer(no_args_is_help=True, help="Manage universes (reusable story settings).")
book_app = typer.Typer(no_args_is_help=True, help="Manage books.")
app.add_typer(universe_app, name="universe")
app.add_typer(book_app, name="book")

console = Console()

_SLUG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_LANG_RE = re.compile(r"[a-z]{2}")

_NOT_IMPLEMENTED = "[yellow]not implemented:[/yellow] {what} arrives in {phase} (spec §15)."


# --------------------------------------------------------------------------- helpers


def _validate_slug(slug: str) -> str:
    if not _SLUG_RE.fullmatch(slug):
        raise typer.BadParameter(f"slug must be kebab-case ([a-z0-9-]), got {slug!r}")
    return slug


def _parse_langs(langs: str) -> list[str]:
    codes = [code.strip() for code in langs.split(",") if code.strip()]
    if not codes:
        raise typer.BadParameter("expected comma-separated ISO 639-1 codes, e.g. 'en,th'")
    for code in codes:
        if not _LANG_RE.fullmatch(code):
            raise typer.BadParameter(f"not an ISO 639-1 language code: {code!r}")
    return codes


def _universes() -> UniverseManager:
    return UniverseManager(Path.cwd() / "Global" / "universes")


def _books() -> BookManager:
    return BookManager(Path.cwd() / "Books")


def _load_universe(slug: str) -> Universe:
    try:
        return _universes().load(slug)
    except NotFoundError as exc:  # unknown universe → usage error (§8.3)
        raise typer.BadParameter(str(exc), param_hint="--universe") from exc


def _load_book(slug: str) -> Book:
    try:
        return _books().load(slug)
    except NotFoundError as exc:  # unknown book → usage error (§8.3)
        raise typer.BadParameter(str(exc), param_hint="SLUG") from exc


def _print_version(value: bool) -> None:
    if value:
        console.print(f"kb {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Show version and exit."
        ),
    ] = False,
) -> None:
    """kb — bilingual illustrated children's books, from idea to print-ready PDF."""


# --------------------------------------------------------------------------- universe


@universe_app.command("list")
def universe_list() -> None:
    """List available universes."""
    universes = _universes().load_all()
    if not universes:
        console.print("No universes found. Create one with [bold]kb universe new[/bold].")
        return
    table = Table("slug", "name", "languages")
    for universe in universes:
        table.add_row(universe.slug, universe.name, ", ".join(universe.languages))
    console.print(table)


@universe_app.command("new")
def universe_new(
    slug: Annotated[str, typer.Argument(help="Kebab-case identifier, e.g. swiss-thai-myths.")],
    name: Annotated[
        str | None, typer.Option("--name", help="Display name; defaults to the title-cased slug.")
    ] = None,
    langs: Annotated[
        str, typer.Option("--langs", help="Comma-separated ISO 639-1 codes.")
    ] = "en,th",
    description: Annotated[str, typer.Option("--description")] = "",
) -> None:
    """Create a new universe."""
    _validate_slug(slug)
    manager = _universes()
    if manager.exists(slug):
        raise typer.BadParameter(f"universe {slug!r} already exists", param_hint="SLUG")
    universe = manager.create(
        slug=slug,
        name=name or slug.replace("-", " ").title(),
        languages=_parse_langs(langs),
        description=description,
    )
    console.print(
        f"Created universe [bold]{universe.slug}[/bold] "
        f"(languages: {', '.join(universe.languages)})."
    )


@universe_app.command("show")
def universe_show(slug: Annotated[str, typer.Argument()]) -> None:
    """Show a universe's details."""
    universe = _load_universe(slug)
    console.print(f"[bold]{universe.name}[/bold] ({universe.slug})")
    console.print(f"languages: {', '.join(universe.languages)}")
    if universe.description:
        console.print(f"description: {universe.description}")
    if universe.style_guide:
        console.print(f"style guide: {universe.style_guide}")


# --------------------------------------------------------------------------- book


@book_app.command("new")
def book_new(
    slug: Annotated[str, typer.Argument(help="Kebab-case identifier, e.g. demo.")],
    universe: Annotated[str, typer.Option("--universe", help="Universe the book belongs to.")],
    langs: Annotated[
        str | None,
        typer.Option("--langs", help="Override the universe's languages (ISO 639-1, e.g. en,th)."),
    ] = None,
    age: Annotated[str, typer.Option("--age", help="Target age group.")] = "4-6",
) -> None:
    """Create a new book from a universe."""
    _validate_slug(slug)
    parent_universe = _load_universe(universe)
    manager = _books()
    if manager.exists(slug):
        raise typer.BadParameter(f"book {slug!r} already exists", param_hint="SLUG")
    book = manager.create(
        slug,
        parent_universe,
        languages=_parse_langs(langs) if langs else None,
        age_group=age,
    )
    console.print(
        f"Created book [bold]{book.slug}[/bold] in universe {parent_universe.slug} "
        f"(languages: {', '.join(book.languages)})."
    )


@book_app.command("list")
def book_list() -> None:
    """List all books."""
    manager = _books()
    slugs = manager.list_slugs()
    if not slugs:
        console.print("No books found. Create one with [bold]kb book new[/bold].")
        return
    table = Table("slug", "title", "universe", "languages", "pages")
    for slug in slugs:
        book = manager.load(slug)
        table.add_row(
            book.slug,
            book.title,
            book.universe_slug,
            ", ".join(book.languages),
            str(len(book.pages)),
        )
    console.print(table)


@book_app.command("status")
def book_status(slug: Annotated[str, typer.Argument()]) -> None:
    """Show pipeline progress for a book."""
    book = _load_book(slug)
    console.print(
        f"[bold]{book.title}[/bold] ({book.slug}) — universe {book.universe_slug}, "
        f"languages: {', '.join(book.languages)}, age group: {book.age_group}"
    )
    if not book.pages:
        console.print("No pages yet — run [bold]kb run[/bold] to start the pipeline.")
        return
    table = Table("page", "status", "text", "image")
    for page in book.pages:
        table.add_row(
            str(page.number),
            page.status,
            ", ".join(sorted(page.text)) or "—",
            str(page.image_path) if page.image_path else "—",
        )
    console.print(table)


@book_app.command("show")
def book_show(slug: Annotated[str, typer.Argument()]) -> None:
    """Show a book's metadata."""
    book = _load_book(slug)
    console.print(f"[bold]{book.title}[/bold] ({book.slug})")
    console.print(f"universe: {book.universe_slug}")
    console.print(f"languages: {', '.join(book.languages)}")
    console.print(f"age group: {book.age_group}")
    console.print(f"characters: {len(book.characters)}, pages: {len(book.pages)}")
    if book.idea:
        console.print(f"idea: {book.idea}")


# --------------------------------------------------------------------------- pipeline


@app.command()
def run(
    slug: Annotated[str, typer.Argument()],
    force: Annotated[
        bool,
        typer.Option(
            "--force", help="Regenerate all selected artifacts, including approved pages."
        ),
    ] = False,
    recreate_images: Annotated[
        bool,
        typer.Option("--recreate-images", help="Regenerate images only; keep texts."),
    ] = False,
    from_page: Annotated[
        int | None,
        typer.Option("--from-page", min=1, help="Restrict page work to pages numbered >= N."),
    ] = None,
    pages: Annotated[
        str | None, typer.Option("--pages", help="Restrict to a page set, e.g. '3,5,7-9'.")
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", help="Confirm between pipeline steps.")
    ] = False,
) -> None:
    """Run the pipeline (Steps 01-05). Idempotent by default (HC-4.1); flags per §8.2."""
    _load_book(slug)
    if pages is not None:
        try:
            parse_page_spec(pages)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--pages") from exc
    console.print(_NOT_IMPLEMENTED.format(what="pipeline steps 01-04", phase="Phase 2"))
    raise typer.Exit(1)


@app.command()
def edit(
    slug: Annotated[str, typer.Argument()],
    page: Annotated[int | None, typer.Option("--page", min=1)] = None,
    text_en: Annotated[str | None, typer.Option("--text-en", help="Replace English text.")] = None,
    text_th: Annotated[str | None, typer.Option("--text-th", help="Replace Thai text.")] = None,
    image: Annotated[
        str | None, typer.Option("--image", help="Regenerate the page image with an instruction.")
    ] = None,
    bible: Annotated[
        str | None, typer.Option("--bible", help="Edit the character bible with an instruction.")
    ] = None,
    approve_page: Annotated[
        int | None, typer.Option("--approve-page", min=1, help="Approve a finished page.")
    ] = None,
) -> None:
    """Edit book content (semantics per §6.2)."""
    _load_book(slug)
    console.print(_NOT_IMPLEMENTED.format(what="editing", phase="Phase 2"))
    raise typer.Exit(1)


@app.command()
def pdf(slug: Annotated[str, typer.Argument()]) -> None:
    """Render the print-ready PDF (spec §11)."""
    _load_book(slug)
    console.print(_NOT_IMPLEMENTED.format(what="PDF rendering", phase="Phase 3"))
    raise typer.Exit(1)


@app.command()
def serve() -> None:
    """Start the local web preview (editor aid only)."""
    console.print(_NOT_IMPLEMENTED.format(what="the web preview", phase="Phase 3"))
    raise typer.Exit(1)


@app.command("open")
def open_book(slug: Annotated[str, typer.Argument()]) -> None:
    """Open a book in the web preview."""
    book = _load_book(slug)
    console.print(f"book files: {_books().book_dir(book.slug)}")
    console.print(_NOT_IMPLEMENTED.format(what="the web preview", phase="Phase 3"))
    raise typer.Exit(1)


# --------------------------------------------------------------------------- entry point


def main() -> None:
    """Console-script entry point; maps errors to exit codes (§8.3)."""
    load_dotenv()
    try:
        setup_logging(Settings.from_env().log_level)
        app()
    except KBError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        raise SystemExit(1) from exc
