"""Interactive, resumable guide from universe idea to reviewed PDF."""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import typer
from rich.console import Console
from rich.table import Table

from kb.config import Settings
from kb.core import editing
from kb.core.book_manager import BookManager
from kb.core.models import Book, Outline, Story, StoryBeat, Universe
from kb.core.steps import bible, outline, pages, story
from kb.core.steps.context import RunOptions, RunResult, StepContext
from kb.core.steps.schemas import BookConceptSpec
from kb.core.universe_manager import UniverseManager
from kb.core.views import write_bible_view
from kb.errors import KBError
from kb.image import create_image_provider
from kb.image.base import ImageProvider
from kb.llm import create_llm_provider
from kb.llm.base import LLMProvider


class AssistantAborted(KBError):
    """Raised when the user deliberately pauses the guided workflow."""


class GuidedAssistant:
    """Review-gated workflow over the normal file-backed pipeline."""

    def __init__(
        self,
        *,
        root: Path,
        settings: Settings,
        console: Console,
    ) -> None:
        self._root = root
        self._settings = settings
        self._console = console
        self._books = BookManager(root / "Books")
        self._universes = UniverseManager(root / "Global" / "universes")
        self._llm: LLMProvider | None = None
        self._images: ImageProvider | None = None

    def run(self, slug: str | None = None) -> Path:
        """Run or resume the assistant and return the final PDF path."""
        if slug is None:
            universe = self._choose_universe()
            self._llm = create_llm_provider(self._settings, languages=universe.languages)
            universe = self._review_universe(universe)
            self._llm = create_llm_provider(self._settings, languages=universe.languages)
            book = self._create_book(universe)
        else:
            book = self._books.load(slug)
            universe = self._universes.load(book.universe_slug)
            self._llm = create_llm_provider(self._settings, languages=book.languages)

        self._images = create_image_provider(self._settings)
        book = self._review_book(book)
        ctx = self._context(book, universe)

        if book.outline is None:
            outline.run(ctx)
        self._review_outline(book)

        if book.story is None:
            story.run(ctx)
        self._review_story(book)

        if not bible.is_done(ctx):
            bible.run(ctx)
        self._review_bible(ctx)

        pages.run(ctx)
        for page in book.pages:
            if page.status != "approved":
                self._review_page(book, universe, page.number)

        return self._review_pdf(book, universe)

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            raise KBError("LLM provider is not initialized")
        return self._llm

    @property
    def images(self) -> ImageProvider:
        if self._images is None:
            raise KBError("image provider is not initialized")
        return self._images

    def _context(self, book: Book, universe: Universe) -> StepContext:
        return StepContext(
            book=book,
            universe=universe,
            books=self._books,
            llm=self.llm,
            images=self.images,
            settings=self._settings,
            options=RunOptions(),
            result=RunResult(),
        )

    def _choose_universe(self) -> Universe:
        universes = self._universes.load_all()
        if universes:
            table = Table("Slug", "Name", "Sprachen")
            for universe in universes:
                table.add_row(universe.slug, universe.name, ", ".join(universe.languages))
            self._console.print("\n[bold]Verfügbare Universen[/bold]")
            self._console.print(table)
        slug = typer.prompt("Universum-Slug (vorhanden oder neu)")
        _validate_slug(slug)
        if self._universes.exists(slug):
            return self._universes.load(slug)

        name = typer.prompt("Name", default=slug.replace("-", " ").title())
        languages = _parse_languages(typer.prompt("Sprachen", default="en,th"))
        description = typer.prompt("Idee und Regeln des Universums")
        style = typer.prompt("Illustrationsstil")
        return self._universes.create(
            slug=slug,
            name=name,
            languages=languages,
            description=description,
            style_guide=style,
        )

    def _review_universe(self, universe: Universe) -> Universe:
        while True:
            self._show_universe(universe)
            action = self._choice("Universum", "[a] freigeben  [m] manuell  [l] LLM  [q] pausieren")
            if action == "a":
                return universe
            if action == "q":
                self._abort()
            if action == "l":
                universe = editing.edit_universe(
                    self._universes, universe, self.llm, typer.prompt("Anweisung an das LLM")
                )
            elif action == "m":
                universe.name = typer.prompt("Name", default=universe.name)
                universe.description = typer.prompt("Beschreibung", default=universe.description)
                universe.languages = _parse_languages(
                    typer.prompt("Sprachen", default=",".join(universe.languages))
                )
                universe.style_guide = typer.prompt(
                    "Illustrationsstil", default=universe.style_guide
                )
                self._universes.save(universe)

    def _create_book(self, universe: Universe) -> Book:
        slug = typer.prompt("Buch-Slug")
        _validate_slug(slug)
        if self._books.exists(slug):
            raise KBError(f"book {slug!r} already exists; resume with `kb assistant {slug}`")
        title = typer.prompt("Arbeitstitel", default=slug.replace("-", " ").title())
        idea = typer.prompt("Buchidee")
        age = typer.prompt("Altersgruppe", default="4-6")
        spreads = typer.prompt("Anzahl Doppelseiten", default=5, type=int)
        book = self._books.create(
            slug,
            universe,
            age_group=age,
            idea=idea,
            spreads=spreads,
        )
        book.title = title
        self._books.save(book)
        return book

    def _review_book(self, book: Book) -> Book:
        while True:
            self._show_book(book)
            action = self._choice("Buchidee", "[a] freigeben  [m] manuell  [l] LLM  [q] pausieren")
            if action == "a":
                return book
            if action == "q":
                self._abort(book.slug)
            if action == "l":
                book = editing.edit_book_concept(
                    self._books, book, self.llm, typer.prompt("Anweisung an das LLM")
                )
            elif action == "m":
                concept = BookConceptSpec(
                    title=typer.prompt("Titel", default=book.title),
                    idea=typer.prompt("Idee", default=book.idea),
                    age_group=typer.prompt("Altersgruppe", default=book.age_group),
                    spreads=typer.prompt("Doppelseiten", default=book.spreads, type=int),
                )
                book = editing.replace_book_concept(self._books, book, concept)

    def _review_outline(self, book: Book) -> None:
        while True:
            assert book.outline is not None
            self._show_outline(book.outline)
            action = self._choice("Outline", "[a] freigeben  [m] manuell  [l] LLM  [q] pausieren")
            if action == "a":
                return
            if action == "q":
                self._abort(book.slug)
            if action == "l":
                editing.edit_outline(
                    self._books, book, self.llm, typer.prompt("Anweisung an das LLM")
                )
            elif action == "m":
                current = book.outline
                synopses = [
                    typer.prompt(f"Doppelseite {number}", default=synopsis)
                    for number, synopsis in enumerate(current.page_synopses, start=1)
                ]
                editing.replace_outline(
                    self._books,
                    book,
                    Outline(
                        title=typer.prompt("Titel", default=current.title),
                        premise=typer.prompt("Prämisse", default=current.premise),
                        page_synopses=synopses,
                    ),
                )

    def _review_story(self, book: Book) -> None:
        while True:
            assert book.story is not None
            self._show_story(book.story)
            action = self._choice("Story", "[a] freigeben  [m] manuell  [l] LLM  [q] pausieren")
            if action == "a":
                return
            if action == "q":
                self._abort(book.slug)
            if action == "l":
                editing.edit_story(
                    self._books, book, self.llm, typer.prompt("Anweisung an das LLM")
                )
            elif action == "m":
                beats = [
                    StoryBeat(
                        narrative=typer.prompt(f"Doppelseite {number}", default=beat.narrative)
                    )
                    for number, beat in enumerate(book.story.beats, start=1)
                ]
                editing.replace_story(self._books, book, Story(beats=beats))

    def _review_bible(self, ctx: StepContext) -> None:
        book = ctx.book
        while True:
            self._show_bible(book)
            action = self._choice(
                "Figurenbibel", "[a] freigeben  [m] manuell  [l] LLM  [r] Bilder neu  [q] pausieren"
            )
            if action == "a":
                return
            if action == "q":
                self._abort(book.slug)
            if action == "r":
                bible.recreate_references(ctx)
            elif action == "l":
                editing.edit_bible(
                    self._books, book, self.llm, typer.prompt("Anweisung an das LLM")
                )
                bible.recreate_references(ctx)
            elif action == "m":
                for character in book.characters:
                    character.name = typer.prompt("Name", default=character.name)
                    character.role = typer.prompt("Rolle", default=character.role)
                    character.description = typer.prompt(
                        "Beschreibung", default=character.description
                    )
                    character.visual_keywords = _parse_list(
                        typer.prompt(
                            "Sichtbare Merkmale",
                            default=", ".join(character.visual_keywords),
                        )
                    )
                self._books.save(book)
                write_bible_view(book, self._books.book_dir(book.slug))
                bible.recreate_references(ctx)

    def _review_page(self, book: Book, universe: Universe, number: int) -> None:
        while True:
            page = editing.get_page(book, number)
            self._show_page(book, number)
            action = self._choice(
                f"Seite {number}",
                "[a] freigeben  [m] Text manuell  [t] Text per LLM  "
                "[i] Bildanweisung  [p] Bildprompt per LLM  [q] pausieren",
            )
            if action == "a":
                if page.status == "approved":
                    return
                editing.approve_page(self._books, book, number)
                return
            if action == "q":
                self._abort(book.slug)
            if action == "m":
                texts = {
                    lang: typer.prompt(f"Text {lang}", default=page.text.get(lang, ""))
                    for lang in book.languages
                }
                editing.edit_text(self._books, book, number, texts)
            elif action == "t":
                editing.rewrite_text(
                    self._books, book, self.llm, number, typer.prompt("Anweisung an das LLM")
                )
            elif action == "i":
                editing.edit_image(
                    self._books,
                    book,
                    universe,
                    self.images,
                    number,
                    typer.prompt("Anweisung an das Bildmodell"),
                )
            elif action == "p":
                editing.rewrite_image_prompt(
                    self._books,
                    book,
                    universe,
                    self.llm,
                    self.images,
                    number,
                    typer.prompt("Anweisung an das LLM"),
                )

    def _review_pdf(self, book: Book, universe: Universe) -> Path:
        from kb.pdf.renderer import render_pdf

        pdf_path = render_pdf(
            book, universe, self._books.book_dir(book.slug), self._root / "Global"
        )
        while True:
            self._console.print(f"\n[bold]PDF[/bold]: {pdf_path}")
            action = self._choice(
                "PDF", "[a] abschließen  [p] Seite erneut prüfen  [r] neu rendern  [q] pausieren"
            )
            if action == "a":
                return pdf_path
            if action == "q":
                self._abort(book.slug)
            if action == "r":
                pdf_path = render_pdf(
                    book, universe, self._books.book_dir(book.slug), self._root / "Global"
                )
            elif action == "p":
                number = typer.prompt("Seitennummer", type=int)
                self._review_page(book, universe, number)
                pdf_path = render_pdf(
                    book, universe, self._books.book_dir(book.slug), self._root / "Global"
                )

    def _choice(self, stage: str, prompt: str) -> str:
        self._console.print(f"[bold]{stage} Review[/bold]  {prompt}")
        allowed = {token[1] for token in prompt.split() if token.startswith("[")}
        while True:
            choice = cast(str, typer.prompt("Auswahl")).strip().lower()
            if choice in allowed:
                return choice
            self._console.print(f"Bitte wählen: {', '.join(sorted(allowed))}")

    def _abort(self, slug: str | None = None) -> None:
        resume = f" Fortsetzen mit: kb assistant {slug}" if slug else ""
        raise AssistantAborted(f"Assistent pausiert; der aktuelle Stand ist gespeichert.{resume}")

    def _show_universe(self, universe: Universe) -> None:
        self._console.print(f"\n[bold]{universe.name}[/bold] ({universe.slug})")
        self._console.print(f"Sprachen: {', '.join(universe.languages)}")
        self._console.print(f"Beschreibung: {universe.description or '—'}")
        self._console.print(f"Stil: {universe.style_guide or '—'}")

    def _show_book(self, book: Book) -> None:
        self._console.print(f"\n[bold]{book.title}[/bold] ({book.slug})")
        self._console.print(f"Idee: {book.idea or '—'}")
        self._console.print(f"Alter: {book.age_group}; Doppelseiten: {book.spreads}")

    def _show_outline(self, value: Outline) -> None:
        self._console.print(f"\n[bold]{value.title}[/bold]\n{value.premise}")
        for number, synopsis in enumerate(value.page_synopses, start=1):
            self._console.print(f"{number}. {synopsis}")

    def _show_story(self, value: Story) -> None:
        self._console.print("\n[bold]Story[/bold]")
        for number, beat in enumerate(value.beats, start=1):
            self._console.print(f"{number}. {beat.narrative}")

    def _show_bible(self, book: Book) -> None:
        self._console.print("\n[bold]Figurenbibel[/bold]")
        for character in book.characters:
            self._console.print(
                f"[bold]{character.name}[/bold] ({character.role})\n"
                f"{character.description}\nMerkmale: {', '.join(character.visual_keywords)}\n"
                f"Referenz: {character.primary_reference or '—'}"
            )

    def _show_page(self, book: Book, number: int) -> None:
        page = editing.get_page(book, number)
        self._console.print(f"\n[bold]Doppelseite {number}[/bold] ({page.status})")
        for lang in book.languages:
            self._console.print(f"[bold]{lang}[/bold]: {page.text.get(lang, '—')}")
        self._console.print(f"Bildprompt: {page.image_prompt or '—'}")
        self._console.print(
            f"Bild: {self._books.book_dir(book.slug) / page.image_path if page.image_path else '—'}"
        )


def _parse_languages(value: str) -> list[str]:
    languages = _parse_list(value)
    if not languages:
        raise typer.BadParameter("mindestens eine Sprache angeben")
    return languages


def _parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_slug(value: str) -> None:
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) is None:
        raise typer.BadParameter(f"Slug muss kebab-case sein, erhalten: {value!r}")
