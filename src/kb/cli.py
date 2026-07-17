"""Command-line interface for kb (spec §8).

Exit codes (§8.3): 0 success, 1 runtime failure, 2 usage error. Unknown
books/universes and invalid ``--pages`` specs are usage errors; pipeline
functionality not yet implemented in the current phase exits 1.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from kb import __version__
from kb.config import Settings
from kb.core import editing
from kb.core.book_manager import BookManager
from kb.core.models import Book, Universe
from kb.core.pagespec import parse_page_spec
from kb.core.pipeline import Pipeline
from kb.core.slug import validate_slug
from kb.core.steps.context import RunOptions
from kb.core.text import clean_text
from kb.core.universe_manager import UniverseManager
from kb.errors import KBError, NotFoundError
from kb.image import create_image_provider
from kb.llm import create_llm_provider
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

_LANG_RE = re.compile(r"[a-z]{2}")


# --------------------------------------------------------------------------- helpers


def _validate_slug(slug: str) -> str:
    try:
        return validate_slug(slug)
    except KBError as exc:
        raise typer.BadParameter(str(exc)) from exc


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


def _load_settings(temperature: float | None) -> Settings:
    """Settings from the environment; ``--temperature`` overrides KB_LLM_TEMPERATURE."""
    settings = Settings.from_env()
    if temperature is not None:
        settings = settings.model_copy(update={"llm_temperature": temperature})
    return settings


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
    style: Annotated[
        str, typer.Option("--style", help="Illustration style guide applied to every image.")
    ] = "",
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
        style_guide=style,
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
    idea: Annotated[
        str, typer.Option("--idea", help="Book idea that seeds the outline (Step 01).")
    ] = "",
    spreads: Annotated[
        int, typer.Option("--spreads", min=1, max=30, help="Number of double-page spreads.")
    ] = 5,
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
        idea=idea,
        spreads=spreads,
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
def book_show(
    slug: Annotated[str, typer.Argument()],
    page: Annotated[
        int | None,
        typer.Option("--page", min=1, help="Show one page in full: text, prompt, status."),
    ] = None,
) -> None:
    """Show a book's metadata, or a single page in full with --page."""
    book = _load_book(slug)
    if page is not None:
        target = next((p for p in book.pages if p.number == page), None)
        if target is None:
            raise typer.BadParameter(f"book {slug!r} has no page {page}", param_hint="--page")
        console.print(f"[bold]{book.title}[/bold] — page {target.number} ({target.status})")
        for lang in book.languages:
            console.print(f"\n[bold]{lang}[/bold]")
            console.print(target.text.get(lang, "[dim]— no text —[/dim]"))
        if target.image_prompt:
            console.print("\n[bold]image prompt[/bold]")
            console.print(target.image_prompt)
        if target.characters_present:
            console.print(f"\ncharacters: {', '.join(target.characters_present)}")
        if target.image_path:
            console.print(f"image: {target.image_path}")
        return
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
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            min=0.0,
            max=1.0,
            help="LLM creativity for this run (0.0-1.0); overrides KB_LLM_TEMPERATURE.",
        ),
    ] = None,
) -> None:
    """Run the pipeline (Steps 01-04). Idempotent by default (HC-4.1); flags per §8.2."""
    book = _load_book(slug)
    selected: set[int] | None = None
    if pages is not None:
        try:
            selected = parse_page_spec(pages)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--pages") from exc

    universe = _load_universe(book.universe_slug)
    settings = _load_settings(temperature)
    options = RunOptions(
        force=force,
        recreate_images=recreate_images,
        from_page=from_page,
        pages=selected,
        interactive=interactive,
    )
    try:
        pipeline = Pipeline(
            books=_books(),
            universe=universe,
            llm=create_llm_provider(settings, languages=book.languages),
            images=create_image_provider(settings),
            settings=settings,
            confirm=typer.confirm if interactive else None,
        )
        result = pipeline.run(book, options)
    except KBError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if result.steps_run:
        console.print(f"Steps run: {', '.join(result.steps_run)}.")
    else:
        console.print("Everything up to date — nothing to do (HC-4.1).")
    if result.pages_texted or result.pages_imaged:
        console.print(
            f"Pages: {result.pages_texted} text(s), {result.pages_imaged} image(s) generated."
        )


@app.command()
def assistant(
    slug: Annotated[
        str | None,
        typer.Argument(help="Existing book to resume; omit to create a universe/book."),
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            min=0.0,
            max=1.0,
            help="Initial LLM creativity (0.0-1.0); adjustable any time by typing "
            "'temp' at a menu.",
        ),
    ] = None,
) -> None:
    """Guide creation from universe or book idea through reviews to the final PDF.

    The current LLM creativity (temperature) is always visible: in the welcome
    panel and in the footer of every action menu. Type 'temp' at any menu to
    change it mid-session; --temperature sets the starting value, otherwise
    KB_LLM_TEMPERATURE from the environment applies.
    """
    from kb.assistant import AssistantAborted, GuidedAssistant

    try:
        path = GuidedAssistant(
            root=Path.cwd(), settings=_load_settings(temperature), console=console
        ).run(slug)
    except AssistantAborted as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return
    except KBError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"Assistent abgeschlossen. PDF: [bold]{path}[/bold]")


@app.command()
def edit(
    slug: Annotated[str, typer.Argument()],
    page: Annotated[int | None, typer.Option("--page", min=1)] = None,
    text: Annotated[
        str | None,
        typer.Option("--text", help="Rewrite the page text (all languages) with an instruction."),
    ] = None,
    text_en: Annotated[str | None, typer.Option("--text-en", help="Replace English text.")] = None,
    text_th: Annotated[str | None, typer.Option("--text-th", help="Replace Thai text.")] = None,
    image: Annotated[
        str | None, typer.Option("--image", help="Regenerate the page image with an instruction.")
    ] = None,
    image_prompt: Annotated[
        str | None,
        typer.Option(
            "--image-prompt",
            help="REPLACE the page's image prompt entirely and regenerate "
            "(use when the safety filter keeps refusing the original scene).",
        ),
    ] = None,
    bible: Annotated[
        str | None, typer.Option("--bible", help="Edit the character bible with an instruction.")
    ] = None,
    approve_page: Annotated[
        int | None, typer.Option("--approve-page", min=1, help="Approve a finished page.")
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            min=0.0,
            max=1.0,
            help="LLM creativity for this edit (0.0-1.0); overrides KB_LLM_TEMPERATURE.",
        ),
    ] = None,
) -> None:
    """Edit book content (semantics per §6.2)."""
    book = _load_book(slug)
    texts = {lang: value for lang, value in (("en", text_en), ("th", text_th)) if value is not None}
    if not (texts or text or image or image_prompt or bible or approve_page):
        raise typer.BadParameter(
            "nothing to do — provide --text, --text-*, --image, --image-prompt, "
            "--bible, or --approve-page"
        )
    if image and image_prompt:
        raise typer.BadParameter("--image and --image-prompt are mutually exclusive")
    if (texts or text or image or image_prompt) and page is None:
        raise typer.BadParameter("--page is required for text and image edits")

    settings = _load_settings(temperature)
    books = _books()
    try:
        if text and page is not None:
            llm = create_llm_provider(settings, languages=book.languages)
            updated = editing.rewrite_text(books, book, llm, page, text)
            console.print(f"Page {page}: text rewritten (status: {updated.status}).")
        if texts and page is not None:
            updated = editing.edit_text(books, book, page, texts)
            console.print(f"Page {page}: text updated (status: {updated.status}).")
        if image and page is not None:
            universe = _load_universe(book.universe_slug)
            editing.edit_image(books, book, universe, create_image_provider(settings), page, image)
            console.print(f"Page {page}: image regenerated (approval revoked, §6.2).")
        if image_prompt and page is not None:
            universe = _load_universe(book.universe_slug)
            editing.edit_image(
                books,
                book,
                universe,
                create_image_provider(settings),
                page,
                image_prompt,
                replace=True,
            )
            console.print(f"Page {page}: image prompt replaced and image regenerated (§6.2).")
        if bible:
            llm = create_llm_provider(settings, languages=book.languages)
            revised = editing.edit_bible(books, book, llm, bible)
            console.print(f"Character bible revised ({len(revised)} characters).")
        if approve_page is not None:
            editing.approve_page(books, book, approve_page)
            console.print(f"Page {approve_page}: approved.")
    except KBError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc


@app.command()
def pdf(slug: Annotated[str, typer.Argument()]) -> None:
    """Render the print-ready PDF (spec §11)."""
    book = _load_book(slug)
    universe = _load_universe(book.universe_slug)
    from kb.pdf.renderer import render_pdf  # deferred: needs Pango/cairo system libs

    try:
        path = render_pdf(book, universe, _books().book_dir(book.slug), Path.cwd() / "Global")
    except KBError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"PDF written to [bold]{path}[/bold]")


@app.command()
def serve(
    host: Annotated[
        str,
        typer.Option("--host", help="Bind address. Use 0.0.0.0 to reach it from outside Docker."),
    ] = "127.0.0.1",
    port: Annotated[
        int, typer.Option("--port", min=1, max=65535, help="Port to listen on.")
    ] = 8000,
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            min=0.0,
            max=1.0,
            help="Initial LLM creativity (0.0-1.0); adjustable any time in the web UI.",
        ),
    ] = None,
) -> None:
    """Start the web editor — full parity with `kb assistant`, plus free navigation
    between stages and books already created.

    Inside Docker, run ``kb serve --host 0.0.0.0`` and publish the port so the
    host browser can reach it (see docker-compose.yml ``ports``); this is also
    the container's default startup command.
    """
    import uvicorn

    from kb.web.app import create_app

    console.print(f"Serving kb editor on [bold]http://{host}:{port}[/bold] (Ctrl+C to stop).")
    uvicorn.run(
        create_app(Path.cwd(), _load_settings(temperature)),
        host=host,
        port=port,
        log_level="warning",
    )


@app.command("open")
def open_book(slug: Annotated[str, typer.Argument()]) -> None:
    """Open a book in the web preview (start `kb serve` first)."""
    import webbrowser

    book = _load_book(slug)
    url = f"http://127.0.0.1:8000/books/{book.slug}"
    console.print(f"Opening {url} — if nothing loads, start [bold]kb serve[/bold] first.")
    webbrowser.open(url)


# --------------------------------------------------------------------------- entry point


def main() -> None:
    """Console-script entry point; maps errors to exit codes (§8.3)."""
    # Repair argv values that arrived through a mis-decoding terminal (e.g. a
    # docker-exec TTY splitting UTF-8 umlauts) before they reach any UTF-8
    # encoder — the same hygiene the assistant applies to interactive input.
    sys.argv = [clean_text(arg) for arg in sys.argv]
    load_dotenv()
    try:
        setup_logging(Settings.from_env().log_level)
        app()
    except KBError as exc:
        Console(stderr=True).print(f"[red]error:[/red] {exc}")
        raise SystemExit(1) from exc
