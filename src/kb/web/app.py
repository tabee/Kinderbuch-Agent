"""Web editor (spec §12) — a local, single-user editing UI with the same
capabilities as `kb assistant`, backed by the same core functions.

Every view renders straight from the YAML file state (HC-4.x): there is no
server-side session, so pausing is just closing the tab and resuming is
loading the URL again. Mutations that call an LLM or image provider run
through a single-slot background job (``jobs.py``) so a request never blocks
for the duration of an API call; everything else (manual edits, approvals,
PDF rendering) is synchronous and effectively instant.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

from kb.config import Settings
from kb.core import editing
from kb.core.book_manager import BookManager
from kb.core.models import Book, Outline, Story, StoryBeat, Universe
from kb.core.slug import validate_slug
from kb.core.steps import bible, outline, pages, story
from kb.core.steps.context import RunOptions, RunResult, StepContext
from kb.core.steps.schemas import BookConceptSpec
from kb.core.text import clean_text
from kb.core.universe_manager import UniverseManager
from kb.core.views import write_bible_view
from kb.errors import KBError, NotFoundError
from kb.image import create_image_provider
from kb.llm import create_llm_provider
from kb.web.jobs import JobRunner

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)

_LANG_RE = re.compile(r"[a-z]{2}")

_STAGE_LABELS = {
    "outline": "Outline",
    "story": "Story",
    "bible": "Figurenbibel",
    "pages": "Seiten",
    "pdf": "Fertig",
}
_STAGE_ACTION_LABELS = {
    "outline": "Outline erzeugen",
    "story": "Story erzeugen",
    "bible": "Figurenbibel erzeugen",
    "pages": "Seiten erzeugen",
}


# --------------------------------------------------------------------------- helpers


def _parse_langs(raw: str) -> list[str]:
    codes = [code.strip() for code in raw.split(",") if code.strip()]
    if not codes or not all(_LANG_RE.fullmatch(code) for code in codes):
        raise KBError(f"languages must be comma-separated ISO 639-1 codes, e.g. 'en,th': {raw!r}")
    return codes


def _parse_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _next_stage(book: Book) -> str:
    """Which stage still needs work — mirrors ``GuidedAssistant``'s resume gating.

    Deliberately independent of any provider: this is called on every page
    view (including the dashboard), and constructing a real provider without
    credentials configured would raise (fail-fast, HC-5.3).
    """
    if book.outline is None:
        return "outline"
    if book.story is None:
        return "story"
    if not book.characters or any(c.primary_reference is None for c in book.characters):
        return "bible"
    if not book.pages or any(p.status != "approved" for p in book.pages):
        return "pages"
    return "pdf"


def _safe_next(path: str) -> str:
    """Only allow same-app relative redirects (avoid open-redirect via the hidden field)."""
    return path if path.startswith("/") and not path.startswith("//") else "/"


def _redirect(url: str, *, ok: str | None = None, err: str | None = None) -> RedirectResponse:
    params = {k: v for k, v in (("ok", ok), ("err", err)) if v}
    if params:
        url = f"{url}?{urlencode(params)}"
    return RedirectResponse(url, status_code=303)


def _render(template: str, request: Request, **context: Any) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    payload: dict[str, Any] = {
        "path": request.url.path,
        "temperature": settings.llm_temperature,
        "ok": request.query_params.get("ok"),
        "err": request.query_params.get("err"),
        **context,
    }
    return HTMLResponse(_env.get_template(template).render(**payload))


def _start_job(
    request: Request, slug: str, description: str, target: Callable[[], None], redirect_to: str
) -> RedirectResponse:
    jobs: JobRunner = request.app.state.jobs
    if jobs.start(slug, description, target) is None:
        return _redirect(redirect_to, err="Es läuft bereits eine Aktion — bitte kurz warten.")
    return _redirect(redirect_to)


def _step_context(
    book: Book, universe: Universe, settings: Settings, books: BookManager
) -> StepContext:
    """Build a StepContext; may raise KBError if a configured provider needs
    credentials that are not set (fail-fast, HC-5.3) — callers must catch it."""
    return StepContext(
        book=book,
        universe=universe,
        books=books,
        llm=create_llm_provider(settings, languages=book.languages),
        images=create_image_provider(settings),
        settings=settings,
        options=RunOptions(),
        result=RunResult(),
    )


def _guard_same_origin(request: Request) -> None:
    """Reject cross-site requests — this server has no authentication (spec §12)."""
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return  # non-browser clients (curl, tests) send no Origin/Referer
    if urlsplit(source).netloc != request.headers.get("host", ""):
        raise HTTPException(status_code=403, detail="cross-origin request blocked")


def create_app(root: Path, settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="kb editor",
        docs_url=None,
        redoc_url=None,
        dependencies=[Depends(_guard_same_origin)],
    )
    app.state.settings = settings or Settings.from_env()
    app.state.jobs = JobRunner()

    books = BookManager(root / "Books")
    universes = UniverseManager(root / "Global" / "universes")

    # ------------------------------------------------------------------ dashboard

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        rows = []
        for slug in books.list_slugs():
            book = books.load(slug)
            stage = _next_stage(book)
            rows.append(
                {
                    "slug": book.slug,
                    "title": book.title,
                    "universe_slug": book.universe_slug,
                    "stage_label": _STAGE_LABELS[stage],
                    "done": stage == "pdf",
                }
            )
        return _render("index.html", request, books=rows, universes=universes.load_all())

    # ------------------------------------------------------------------ universes

    @app.get("/universes/new", response_class=HTMLResponse)
    async def universe_new_form(request: Request) -> HTMLResponse:
        return _render("universe.html", request, universe=None, job=None)

    @app.post("/universes/new")
    async def universe_new(
        slug: Annotated[str, Form()],
        name: Annotated[str, Form()] = "",
        languages: Annotated[str, Form()] = "en,th",
        description: Annotated[str, Form()] = "",
        style_guide: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        clean_slug = clean_text(slug)
        try:
            validate_slug(clean_slug)
            if universes.exists(clean_slug):
                raise KBError(f"universe {clean_slug!r} already exists")
            langs = _parse_langs(languages)
            universe = universes.create(
                slug=clean_slug,
                name=clean_text(name) or clean_slug.replace("-", " ").title(),
                languages=langs,
                description=clean_text(description),
                style_guide=clean_text(style_guide),
            )
        except KBError as exc:
            return _redirect("/universes/new", err=str(exc))
        return _redirect(f"/universes/{universe.slug}", ok="Universum angelegt.")

    @app.get("/universes/{slug}", response_class=HTMLResponse)
    async def universe_view(slug: str, request: Request) -> HTMLResponse:
        try:
            universe = universes.load(slug)
        except NotFoundError:
            return HTMLResponse(f"unknown universe: {html.escape(slug)}", status_code=404)
        jobs: JobRunner = request.app.state.jobs
        job = jobs.current
        if job is not None and job.slug == slug and job.done:
            jobs.clear(job)
        return _render("universe.html", request, universe=universe, job=job)

    @app.post("/universes/{slug}/edit")
    async def universe_edit(
        slug: str,
        name: Annotated[str, Form()],
        languages: Annotated[str, Form()],
        description: Annotated[str, Form()] = "",
        style_guide: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        universe = universes.load(slug)
        try:
            langs = _parse_langs(languages)
        except KBError as exc:
            return _redirect(f"/universes/{slug}", err=str(exc))
        universe.name = clean_text(name)
        universe.languages = langs
        universe.description = clean_text(description)
        universe.style_guide = clean_text(style_guide)
        universes.save(universe)
        return _redirect(f"/universes/{slug}", ok="Universum gespeichert.")

    @app.post("/universes/{slug}/revise")
    async def universe_revise(
        slug: str, request: Request, instruction: Annotated[str, Form()]
    ) -> RedirectResponse:
        universe = universes.load(slug)
        settings: Settings = request.app.state.settings
        try:
            llm = create_llm_provider(settings, languages=universe.languages)
        except KBError as exc:
            return _redirect(f"/universes/{slug}", err=str(exc))
        clean_instruction = clean_text(instruction)

        def target() -> None:
            editing.edit_universe(universes, universe, llm, clean_instruction)

        return _start_job(
            request, slug, "Universum wird überarbeitet …", target, f"/universes/{slug}"
        )

    # ------------------------------------------------------------------ books

    @app.get("/books/new", response_class=HTMLResponse)
    async def book_new_form(request: Request) -> HTMLResponse:
        return _render("book_new.html", request, universes=universes.load_all())

    @app.post("/books/new")
    async def book_new(
        slug: Annotated[str, Form()],
        universe_slug: Annotated[str, Form()],
        title: Annotated[str, Form()] = "",
        idea: Annotated[str, Form()] = "",
        age_group: Annotated[str, Form()] = "4-6",
        spreads: Annotated[int, Form(ge=1, le=30)] = 5,
    ) -> RedirectResponse:
        clean_slug = clean_text(slug)
        try:
            validate_slug(clean_slug)
            if books.exists(clean_slug):
                raise KBError(f"book {clean_slug!r} already exists")
            parent = universes.load(universe_slug)
            book = books.create(
                clean_slug,
                parent,
                age_group=clean_text(age_group) or "4-6",
                idea=clean_text(idea),
                spreads=spreads,
            )
            clean_title = clean_text(title)
            if clean_title:
                book.title = clean_title
                books.save(book)
        except KBError as exc:
            return _redirect("/books/new", err=str(exc))
        return _redirect(f"/books/{book.slug}", ok="Buch angelegt.")

    @app.get("/books/{slug}", response_class=HTMLResponse)
    async def book_view(slug: str, request: Request) -> HTMLResponse:
        try:
            book = books.load(slug)
        except NotFoundError:
            return HTMLResponse(f"unknown book: {html.escape(slug)}", status_code=404)
        universe = universes.load(book.universe_slug)
        stage = _next_stage(book)
        jobs: JobRunner = request.app.state.jobs
        job = jobs.current
        if job is not None and job.slug == slug and job.done:
            jobs.clear(job)
        pdf_path = books.book_dir(slug) / "build" / f"{slug}.pdf"
        return _render(
            "book.html",
            request,
            book=book,
            universe=universe,
            current_stage=stage,
            stage_action_label=_STAGE_ACTION_LABELS.get(stage, ""),
            job=job,
            pdf_exists=pdf_path.is_file(),
        )

    # ------------------------------------------------------------------ book concept

    @app.post("/books/{slug}/concept/edit")
    async def concept_edit(
        slug: str,
        title: Annotated[str, Form()],
        idea: Annotated[str, Form()] = "",
        age_group: Annotated[str, Form()] = "4-6",
        spreads: Annotated[int, Form(ge=1, le=30)] = 5,
    ) -> RedirectResponse:
        book = books.load(slug)
        try:
            concept = BookConceptSpec(
                title=clean_text(title),
                idea=clean_text(idea),
                age_group=clean_text(age_group),
                spreads=spreads,
            )
            editing.replace_book_concept(books, book, concept)
        except (KBError, ValidationError) as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        return _redirect(f"/books/{slug}", ok="Buchidee gespeichert.")

    @app.post("/books/{slug}/concept/revise")
    async def concept_revise(
        slug: str, request: Request, instruction: Annotated[str, Form()]
    ) -> RedirectResponse:
        book = books.load(slug)
        settings: Settings = request.app.state.settings
        try:
            llm = create_llm_provider(settings, languages=book.languages)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        clean_instruction = clean_text(instruction)

        def target() -> None:
            editing.edit_book_concept(books, book, llm, clean_instruction)

        return _start_job(request, slug, "Buchidee wird überarbeitet …", target, f"/books/{slug}")

    # ------------------------------------------------------------------ outline

    @app.post("/books/{slug}/outline/edit")
    async def outline_edit(slug: str, request: Request) -> RedirectResponse:
        book = books.load(slug)
        if book.outline is None:
            return _redirect(f"/books/{slug}", err="Es gibt noch keine Outline.")
        form = await request.form()
        synopses = [
            clean_text(str(form.get(f"synopsis_{i}", synopsis)))
            for i, synopsis in enumerate(book.outline.page_synopses, start=1)
        ]
        revised = Outline(
            title=clean_text(str(form.get("title", book.outline.title))),
            premise=clean_text(str(form.get("premise", book.outline.premise))),
            page_synopses=synopses,
        )
        try:
            editing.replace_outline(books, book, revised)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        return _redirect(f"/books/{slug}", ok="Outline gespeichert.")

    @app.post("/books/{slug}/outline/revise")
    async def outline_revise(
        slug: str, request: Request, instruction: Annotated[str, Form()]
    ) -> RedirectResponse:
        book = books.load(slug)
        if book.outline is None:
            return _redirect(f"/books/{slug}", err="Es gibt noch keine Outline.")
        settings: Settings = request.app.state.settings
        try:
            llm = create_llm_provider(settings, languages=book.languages)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        clean_instruction = clean_text(instruction)

        def target() -> None:
            editing.edit_outline(books, book, llm, clean_instruction)

        return _start_job(request, slug, "Outline wird überarbeitet …", target, f"/books/{slug}")

    # ------------------------------------------------------------------ story

    @app.post("/books/{slug}/story/edit")
    async def story_edit(slug: str, request: Request) -> RedirectResponse:
        book = books.load(slug)
        if book.story is None:
            return _redirect(f"/books/{slug}", err="Es gibt noch keine Story.")
        form = await request.form()
        beats = [
            StoryBeat(narrative=clean_text(str(form.get(f"beat_{i}", beat.narrative))))
            for i, beat in enumerate(book.story.beats, start=1)
        ]
        try:
            editing.replace_story(books, book, Story(beats=beats))
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        return _redirect(f"/books/{slug}", ok="Story gespeichert.")

    @app.post("/books/{slug}/story/revise")
    async def story_revise(
        slug: str, request: Request, instruction: Annotated[str, Form()]
    ) -> RedirectResponse:
        book = books.load(slug)
        if book.story is None:
            return _redirect(f"/books/{slug}", err="Es gibt noch keine Story.")
        settings: Settings = request.app.state.settings
        try:
            llm = create_llm_provider(settings, languages=book.languages)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        clean_instruction = clean_text(instruction)

        def target() -> None:
            editing.edit_story(books, book, llm, clean_instruction)

        return _start_job(request, slug, "Story wird überarbeitet …", target, f"/books/{slug}")

    # ------------------------------------------------------------------ bible

    @app.post("/books/{slug}/bible/edit")
    async def bible_edit(slug: str, request: Request) -> RedirectResponse:
        book = books.load(slug)
        universe = universes.load(book.universe_slug)
        settings: Settings = request.app.state.settings
        try:
            ctx = _step_context(book, universe, settings, books)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        form = await request.form()
        for i, character in enumerate(book.characters, start=1):
            character.name = clean_text(str(form.get(f"name_{i}", character.name)))
            character.role = clean_text(str(form.get(f"role_{i}", character.role)))
            character.description = clean_text(
                str(form.get(f"description_{i}", character.description))
            )
            character.visual_keywords = _parse_list(clean_text(str(form.get(f"keywords_{i}", ""))))
        books.save(book)
        write_bible_view(book, books.book_dir(slug))

        def target() -> None:
            bible.recreate_references(ctx)

        return _start_job(
            request, slug, "Referenzbilder werden neu gezeichnet …", target, f"/books/{slug}"
        )

    @app.post("/books/{slug}/bible/revise")
    async def bible_revise(
        slug: str, request: Request, instruction: Annotated[str, Form()]
    ) -> RedirectResponse:
        book = books.load(slug)
        universe = universes.load(book.universe_slug)
        settings: Settings = request.app.state.settings
        try:
            ctx = _step_context(book, universe, settings, books)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        clean_instruction = clean_text(instruction)

        def target() -> None:
            editing.edit_bible(books, book, ctx.llm, clean_instruction)
            bible.recreate_references(ctx)

        return _start_job(
            request, slug, "Figurenbibel wird überarbeitet …", target, f"/books/{slug}"
        )

    @app.post("/books/{slug}/bible/references")
    async def bible_references(slug: str, request: Request) -> RedirectResponse:
        book = books.load(slug)
        universe = universes.load(book.universe_slug)
        settings: Settings = request.app.state.settings
        try:
            ctx = _step_context(book, universe, settings, books)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))

        def target() -> None:
            bible.recreate_references(ctx)

        return _start_job(
            request, slug, "Referenzbilder werden neu gezeichnet …", target, f"/books/{slug}"
        )

    # ------------------------------------------------------------------ generate next stage

    @app.post("/books/{slug}/generate")
    async def book_generate(slug: str, request: Request) -> RedirectResponse:
        book = books.load(slug)
        universe = universes.load(book.universe_slug)
        settings: Settings = request.app.state.settings
        stage = _next_stage(book)
        if stage == "pdf":
            return _redirect(f"/books/{slug}", err="Nichts zu erzeugen — das Buch ist vollständig.")
        try:
            ctx = _step_context(book, universe, settings, books)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))

        def target() -> None:
            if stage == "outline":
                outline.run(ctx)
            elif stage == "story":
                story.run(ctx)
            elif stage == "bible":
                bible.run(ctx)
            else:
                pages.run(ctx)

        return _start_job(
            request, slug, f"{_STAGE_ACTION_LABELS[stage]} …", target, f"/books/{slug}"
        )

    # ------------------------------------------------------------------ pages

    @app.post("/books/{slug}/pages/{number}/approve")
    async def page_approve(slug: str, number: int) -> RedirectResponse:
        book = books.load(slug)
        try:
            editing.approve_page(books, book, number)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        return _redirect(f"/books/{slug}", ok=f"Seite {number} freigegeben.")

    @app.post("/books/{slug}/pages/{number}/text")
    async def page_text(slug: str, number: int, request: Request) -> RedirectResponse:
        book = books.load(slug)
        form = await request.form()
        texts = {lang: clean_text(str(form.get(f"text_{lang}", ""))) for lang in book.languages}
        try:
            editing.edit_text(books, book, number, texts)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        return _redirect(f"/books/{slug}", ok=f"Seite {number}: Text ersetzt.")

    @app.post("/books/{slug}/pages/{number}/rewrite")
    async def page_rewrite(
        slug: str, number: int, request: Request, instruction: Annotated[str, Form()]
    ) -> RedirectResponse:
        book = books.load(slug)
        settings: Settings = request.app.state.settings
        try:
            llm = create_llm_provider(settings, languages=book.languages)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        clean_instruction = clean_text(instruction)

        def target() -> None:
            editing.rewrite_text(books, book, llm, number, clean_instruction)

        return _start_job(
            request, slug, f"Text von Seite {number} wird umgeschrieben …", target, f"/books/{slug}"
        )

    @app.post("/books/{slug}/pages/{number}/image")
    async def page_image(
        slug: str, number: int, request: Request, instruction: Annotated[str, Form()]
    ) -> RedirectResponse:
        book = books.load(slug)
        universe = universes.load(book.universe_slug)
        settings: Settings = request.app.state.settings
        try:
            images = create_image_provider(settings)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        clean_instruction = clean_text(instruction)

        def target() -> None:
            editing.edit_image(books, book, universe, images, number, clean_instruction)

        return _start_job(
            request, slug, f"Bild von Seite {number} wird neu erzeugt …", target, f"/books/{slug}"
        )

    @app.post("/books/{slug}/pages/{number}/image-prompt")
    async def page_image_prompt(
        slug: str, number: int, request: Request, instruction: Annotated[str, Form()]
    ) -> RedirectResponse:
        book = books.load(slug)
        universe = universes.load(book.universe_slug)
        settings: Settings = request.app.state.settings
        try:
            llm = create_llm_provider(settings, languages=book.languages)
            images = create_image_provider(settings)
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        clean_instruction = clean_text(instruction)

        def target() -> None:
            editing.rewrite_image_prompt(
                books, book, universe, llm, images, number, clean_instruction
            )

        return _start_job(
            request,
            slug,
            f"Bildprompt von Seite {number} wird ersetzt …",
            target,
            f"/books/{slug}",
        )

    # ------------------------------------------------------------------ pdf

    @app.post("/books/{slug}/pdf")
    async def book_pdf(slug: str) -> RedirectResponse:
        from kb.pdf.renderer import render_pdf  # deferred: needs Pango/cairo system libs

        book = books.load(slug)
        universe = universes.load(book.universe_slug)
        try:
            render_pdf(book, universe, books.book_dir(slug), root / "Global")
        except KBError as exc:
            return _redirect(f"/books/{slug}", err=str(exc))
        return _redirect(f"/books/{slug}", ok="PDF gerendert.")

    # ------------------------------------------------------------------ settings

    @app.post("/settings/temperature")
    async def set_temperature(
        request: Request,
        temperature: Annotated[str, Form()] = "",
        next_url: Annotated[str, Form()] = "/",
    ) -> RedirectResponse:
        target_url = _safe_next(next_url)
        raw = temperature.strip().replace(",", ".")
        value: float | None = None
        if raw:
            try:
                value = float(raw)
            except ValueError:
                return _redirect(target_url, err=f"Keine Zahl: {raw!r}")
            if not 0.0 <= value <= 1.0:
                return _redirect(target_url, err="Kreativität muss zwischen 0.0 und 1.0 liegen.")
        request.app.state.settings = request.app.state.settings.model_copy(
            update={"llm_temperature": value}
        )
        return _redirect(target_url, ok="Kreativität aktualisiert.")

    # ------------------------------------------------------------------ files

    @app.get("/books/{slug}/files/{file_path:path}")
    async def book_file(slug: str, file_path: str) -> FileResponse:
        book_dir = books.book_dir(slug).resolve()
        target = (book_dir / file_path).resolve()
        if not target.is_relative_to(book_dir) or not target.is_file():  # path traversal guard
            return HTMLResponse("not found", status_code=404)  # type: ignore[return-value]
        return FileResponse(target)

    return app
