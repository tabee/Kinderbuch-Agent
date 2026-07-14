"""Interactive, resumable guide from universe idea to reviewed PDF."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.status import Status
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


@dataclass(frozen=True)
class _Action:
    """One selectable review action; chosen by number, key letter, or word."""

    key: str
    label: str
    description: str
    words: tuple[str, ...] = ()


_APPROVE = _Action(
    "a",
    "Freigeben",
    "Diesen Stand übernehmen und zum nächsten Schritt gehen",
    ("freigeben", "ok", "ja", "weiter"),
)
_MANUAL = _Action(
    "m",
    "Manuell bearbeiten",
    "Jedes Feld selbst ändern — Enter behält den aktuellen Wert",
    ("manuell", "bearbeiten"),
)
_REVISE = _Action(
    "l",
    "Vom LLM überarbeiten lassen",
    "Freie Anweisung geben; das LLM schreibt eine neue Fassung",
    ("llm", "anweisung"),
)
_PAUSE = _Action(
    "q",
    "Pausieren",
    "Alles ist gespeichert — später fortsetzen mit 'kb assistant <slug>'",
    ("pausieren", "pause", "quit", "exit", "stop"),
)
_STANDARD_ACTIONS = (_APPROVE, _MANUAL, _REVISE, _PAUSE)

_BIBLE_ACTIONS = (
    _APPROVE,
    _MANUAL,
    _REVISE,
    _Action(
        "r",
        "Referenzbilder neu zeichnen",
        "Bibeltext behalten, alle Referenzbilder neu erzeugen",
        ("referenzen", "bilder"),
    ),
    _PAUSE,
)

_PAGE_ACTIONS = (
    _Action(
        "a",
        "Seite freigeben",
        "Text und Bild passen — die Seite wird als 'approved' gesperrt",
        ("freigeben", "ok", "ja", "weiter"),
    ),
    _Action(
        "m",
        "Text manuell ersetzen",
        "Den Text jeder Sprache selbst eintippen",
        ("manuell",),
    ),
    _Action(
        "t",
        "Text vom LLM umschreiben",
        "Anweisung geben; alle Sprachen werden konsistent neu geschrieben",
        ("llm", "text"),
    ),
    _Action(
        "i",
        "Bild anpassen",
        "Anweisung wird an den Bildprompt angehängt, das Bild neu erzeugt",
        ("bild",),
    ),
    _Action(
        "p",
        "Bildprompt neu schreiben",
        "LLM ersetzt den Prompt komplett — der Ausweg bei Safety-Refusals",
        ("prompt", "bildprompt"),
    ),
    _PAUSE,
)

_PDF_ACTIONS = (
    _Action(
        "a",
        "Abschließen",
        "Assistent beenden — das PDF ist fertig",
        ("abschließen", "fertig", "ok", "ja"),
    ),
    _Action(
        "p",
        "Seite nachbessern",
        "Eine Seite erneut öffnen; danach wird das PDF neu gerendert",
        ("seite",),
    ),
    _Action(
        "r",
        "PDF neu rendern",
        "Layout und Schriften erneut setzen (kostenlos)",
        ("rendern", "neu"),
    ),
    _PAUSE,
)

_STAGES = ("Universum", "Buchidee", "Outline", "Story", "Figurenbibel", "Seiten", "PDF")


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
        self._welcome(slug)
        if slug is None:
            self._stage("Universum")
            universe = self._choose_universe()
            self._llm = create_llm_provider(self._settings, languages=universe.languages)
            universe = self._review_universe(universe)
            self._llm = create_llm_provider(self._settings, languages=universe.languages)
            self._stage("Buchidee")
            book = self._create_book(universe)
        else:
            book = self._books.load(slug)
            universe = self._universes.load(book.universe_slug)
            self._llm = create_llm_provider(self._settings, languages=book.languages)
            self._stage("Buchidee")

        self._images = create_image_provider(self._settings)
        book = self._review_book(book)
        ctx = self._context(book, universe)

        self._stage("Outline")
        if book.outline is None:
            with self._work("Outline wird erzeugt …"):
                outline.run(ctx)
        self._review_outline(book)

        self._stage("Story")
        if book.story is None:
            with self._work("Story wird geschrieben …"):
                story.run(ctx)
        self._review_story(book)

        self._stage("Figurenbibel")
        if not bible.is_done(ctx):
            with self._work("Figurenbibel und Referenzbilder werden erzeugt …"):
                bible.run(ctx)
        self._review_bible(ctx)

        with self._work("Seitentexte und Illustrationen werden erzeugt …"):
            pages.run(ctx)
        total = len(book.pages)
        for page in book.pages:
            if page.status != "approved":
                self._stage("Seiten", f"Seite {page.number} von {total}")
                self._review_page(book, universe, page.number)

        self._stage("PDF")
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
            table = Table(box=None, padding=(0, 2), header_style="bold")
            table.add_column("Slug", style="cyan")
            table.add_column("Name")
            table.add_column("Sprachen", style="dim")
            for universe in universes:
                table.add_row(universe.slug, escape(universe.name), ", ".join(universe.languages))
            self._console.print(
                Panel(
                    table,
                    title="[bold]Verfügbare Universen[/bold]",
                    title_align="left",
                    border_style="dim",
                )
            )
        self._console.print(
            "[dim]Vorhandenen Slug wählen — oder einen neuen eingeben, "
            "um ein Universum anzulegen.[/dim]"
        )
        slug = cast(str, typer.prompt("Universum-Slug (vorhanden oder neu)"))
        _validate_slug(slug)
        if self._universes.exists(slug):
            self._done(f"Universum [bold]{slug}[/bold] geladen.")
            return self._universes.load(slug)

        self._console.print(f"[bold]{slug}[/bold] ist neu — lege das Universum jetzt an.")
        name = typer.prompt("Name", default=slug.replace("-", " ").title())
        languages = self._prompt_languages("en,th")
        description = typer.prompt("Idee und Regeln des Universums")
        style = typer.prompt("Illustrationsstil (gilt für jedes Bild)")
        universe = self._universes.create(
            slug=slug,
            name=name,
            languages=languages,
            description=description,
            style_guide=style,
        )
        self._done(f"Universum [bold]{slug}[/bold] angelegt.")
        return universe

    def _review_universe(self, universe: Universe) -> Universe:
        while True:
            self._show_universe(universe)
            action = self._ask(_STANDARD_ACTIONS)
            if action == "a":
                self._done("Universum freigegeben.")
                return universe
            if action == "q":
                self._abort()
            if action == "l":
                instruction = self._instruction(
                    "z. B. 'düsterer und geheimnisvoller' oder 'Stil: grobe Buntstift-Texturen'"
                )
                with self._work("Das LLM überarbeitet das Universum …"):
                    universe = editing.edit_universe(
                        self._universes, universe, self.llm, instruction
                    )
                self._done("Universum überarbeitet — bitte prüfen.")
            elif action == "m":
                universe.name = typer.prompt("Name", default=universe.name)
                universe.description = typer.prompt("Beschreibung", default=universe.description)
                universe.languages = self._prompt_languages(",".join(universe.languages))
                universe.style_guide = typer.prompt(
                    "Illustrationsstil", default=universe.style_guide
                )
                self._universes.save(universe)
                self._done("Änderungen gespeichert — bitte prüfen.")

    def _create_book(self, universe: Universe) -> Book:
        self._console.print(
            "[dim]Der Slug wird Ordnername unter Books/ — kebab-case, z. B. 'ninos-berge'.[/dim]"
        )
        slug = cast(str, typer.prompt("Buch-Slug"))
        _validate_slug(slug)
        if self._books.exists(slug):
            raise KBError(f"book {slug!r} already exists; resume with `kb assistant {slug}`")
        title = typer.prompt("Arbeitstitel", default=slug.replace("-", " ").title())
        idea = typer.prompt("Buchidee (der wichtigste kreative Input)")
        age = typer.prompt("Altersgruppe", default="4-6")
        spreads = self._prompt_spreads(5)
        book = self._books.create(
            slug,
            universe,
            age_group=age,
            idea=idea,
            spreads=spreads,
        )
        book.title = title
        self._books.save(book)
        self._done(f"Buch [bold]{slug}[/bold] angelegt.")
        return book

    def _review_book(self, book: Book) -> Book:
        while True:
            self._show_book(book)
            action = self._ask(_STANDARD_ACTIONS)
            if action == "a":
                self._done("Buchidee freigegeben.")
                return book
            if action == "q":
                self._abort(book.slug)
            if action == "l":
                instruction = self._instruction(
                    "z. B. 'mach den Helden mutiger' oder 'die Reise soll im Winter spielen'"
                )
                with self._work("Das LLM überarbeitet die Buchidee …"):
                    book = editing.edit_book_concept(self._books, book, self.llm, instruction)
                self._done("Buchidee überarbeitet — bitte prüfen.")
            elif action == "m":
                concept = BookConceptSpec(
                    title=typer.prompt("Titel", default=book.title),
                    idea=typer.prompt("Idee", default=book.idea),
                    age_group=typer.prompt("Altersgruppe", default=book.age_group),
                    spreads=self._prompt_spreads(book.spreads),
                )
                book = editing.replace_book_concept(self._books, book, concept)
                self._done("Änderungen gespeichert — bitte prüfen.")

    def _review_outline(self, book: Book) -> None:
        while True:
            assert book.outline is not None
            self._show_outline(book.outline)
            action = self._ask(_STANDARD_ACTIONS)
            if action == "a":
                self._done("Outline freigegeben.")
                return
            if action == "q":
                self._abort(book.slug)
            if action == "l":
                instruction = self._instruction(
                    "z. B. 'mehr Spannung ab Seite 3' oder 'das Ende soll überraschen'"
                )
                with self._work("Das LLM überarbeitet die Outline …"):
                    editing.edit_outline(self._books, book, self.llm, instruction)
                self._done("Outline überarbeitet — bitte prüfen.")
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
                self._done("Änderungen gespeichert — bitte prüfen.")

    def _review_story(self, book: Book) -> None:
        while True:
            assert book.story is not None
            self._show_story(book.story)
            action = self._ask(_STANDARD_ACTIONS)
            if action == "a":
                self._done("Story freigegeben.")
                return
            if action == "q":
                self._abort(book.slug)
            if action == "l":
                instruction = self._instruction(
                    "z. B. 'kürzere Sätze' oder 'mehr Dialog zwischen den Figuren'"
                )
                with self._work("Das LLM überarbeitet die Story …"):
                    editing.edit_story(self._books, book, self.llm, instruction)
                self._done("Story überarbeitet — bitte prüfen.")
            elif action == "m":
                beats = [
                    StoryBeat(
                        narrative=typer.prompt(f"Doppelseite {number}", default=beat.narrative)
                    )
                    for number, beat in enumerate(book.story.beats, start=1)
                ]
                editing.replace_story(self._books, book, Story(beats=beats))
                self._done("Änderungen gespeichert — bitte prüfen.")

    def _review_bible(self, ctx: StepContext) -> None:
        book = ctx.book
        while True:
            self._show_bible(book)
            action = self._ask(_BIBLE_ACTIONS)
            if action == "a":
                self._done("Figurenbibel freigegeben.")
                return
            if action == "q":
                self._abort(book.slug)
            if action == "r":
                with self._work("Referenzbilder werden neu gezeichnet …"):
                    bible.recreate_references(ctx)
                self._done("Referenzbilder erneuert — bitte prüfen.")
            elif action == "l":
                instruction = self._instruction(
                    "z. B. 'gib der Naga einen roten Schal' oder 'die Oma wirkt zu streng'"
                )
                with self._work("Das LLM überarbeitet die Bibel, Referenzen werden neu …"):
                    editing.edit_bible(self._books, book, self.llm, instruction)
                    bible.recreate_references(ctx)
                self._done("Figurenbibel überarbeitet — bitte prüfen.")
            elif action == "m":
                for character in book.characters:
                    self._console.print(f"\n[bold cyan]{character.name}[/bold cyan]")
                    character.name = typer.prompt("Name", default=character.name)
                    character.role = typer.prompt("Rolle", default=character.role)
                    character.description = typer.prompt(
                        "Beschreibung", default=character.description
                    )
                    character.visual_keywords = _parse_list(
                        typer.prompt(
                            "Sichtbare Merkmale (kommagetrennt)",
                            default=", ".join(character.visual_keywords),
                        )
                    )
                self._books.save(book)
                write_bible_view(book, self._books.book_dir(book.slug))
                with self._work("Referenzbilder werden neu gezeichnet …"):
                    bible.recreate_references(ctx)
                self._done("Änderungen gespeichert, Referenzen erneuert — bitte prüfen.")

    def _review_page(self, book: Book, universe: Universe, number: int) -> None:
        while True:
            page = editing.get_page(book, number)
            self._show_page(book, number)
            action = self._ask(_PAGE_ACTIONS)
            if action == "q":
                self._abort(book.slug)
            try:
                if action == "a":
                    if page.status != "approved":
                        editing.approve_page(self._books, book, number)
                    self._done(f"Seite {number} freigegeben.")
                    return
                if action == "m":
                    texts = {
                        lang: typer.prompt(f"Text {lang}", default=page.text.get(lang, ""))
                        for lang in book.languages
                    }
                    editing.edit_text(self._books, book, number, texts)
                    self._done("Text ersetzt — bitte prüfen.")
                elif action == "t":
                    instruction = self._instruction(
                        "z. B. 'kürzer und lustiger' oder 'HARD LIMIT: 60 Wörter pro Sprache'"
                    )
                    with self._work("Das LLM schreibt den Text neu …"):
                        editing.rewrite_text(self._books, book, self.llm, number, instruction)
                    self._done("Text neu geschrieben — bitte prüfen.")
                elif action == "i":
                    instruction = self._instruction(
                        "z. B. 'mehr Schnee, warmes Abendlicht' — wird an den Prompt angehängt"
                    )
                    with self._work("Das Bild wird neu erzeugt …"):
                        editing.edit_image(
                            self._books, book, universe, self.images, number, instruction
                        )
                    self._done("Bild neu erzeugt — bitte prüfen.")
                elif action == "p":
                    instruction = self._instruction(
                        "z. B. 'ruhigere Szene am Seeufer, kein Sturm' — ersetzt den Prompt"
                    )
                    with self._work("Neuer Bildprompt und neues Bild …"):
                        editing.rewrite_image_prompt(
                            self._books, book, universe, self.llm, self.images, number, instruction
                        )
                    self._done("Bildprompt ersetzt, Bild neu erzeugt — bitte prüfen.")
            except KBError as exc:
                self._console.print(f"[red]Fehler:[/red] {exc}")

    def _review_pdf(self, book: Book, universe: Universe) -> Path:
        from kb.pdf.renderer import render_pdf

        with self._work("PDF wird gerendert …"):
            pdf_path = render_pdf(
                book, universe, self._books.book_dir(book.slug), self._root / "Global"
            )
        while True:
            self._console.print(
                Panel(
                    f"[bold green]{pdf_path}[/bold green]\n"
                    f"[dim]216 x 216 mm, 3 mm Beschnitt, eingebettete Noto-Schriften — "
                    f"druckfertig.[/dim]",
                    title="[bold]Fertiges PDF[/bold]",
                    title_align="left",
                    border_style="green",
                )
            )
            action = self._ask(_PDF_ACTIONS)
            if action == "a":
                return pdf_path
            if action == "q":
                self._abort(book.slug)
            if action == "r":
                with self._work("PDF wird neu gerendert …"):
                    pdf_path = render_pdf(
                        book, universe, self._books.book_dir(book.slug), self._root / "Global"
                    )
            elif action == "p":
                number = cast(int, typer.prompt("Seitennummer", type=int))
                if not any(p.number == number for p in book.pages):
                    self._console.print(
                        f"[red]Seite {number} gibt es nicht[/red] — gültig: 1-{len(book.pages)}."
                    )
                    continue
                self._review_page(book, universe, number)
                with self._work("PDF wird neu gerendert …"):
                    pdf_path = render_pdf(
                        book, universe, self._books.book_dir(book.slug), self._root / "Global"
                    )

    # ------------------------------------------------------------------ UI helpers

    def _welcome(self, slug: str | None) -> None:
        mode = (
            f"Buch [bold]{slug}[/bold] wird fortgesetzt — bereits Erledigtes wird übersprungen."
            if slug
            else "Ein neues Buch entsteht — vom Universum bis zum druckfertigen PDF."
        )
        self._console.print(
            Panel(
                f"{mode}\n\n"
                "[bold]Ablauf:[/bold]  " + "  →  ".join(_STAGES) + "\n"
                "[dim]Nach jedem Schritt prüfst du das Ergebnis: freigeben, selbst ändern "
                "oder vom LLM überarbeiten lassen. Jeder Stand wird sofort gespeichert — "
                "Pausieren ist jederzeit verlustfrei möglich.[/dim]",
                title="[bold cyan]kb Assistent[/bold cyan]",
                title_align="left",
                border_style="cyan",
            )
        )

    def _stage(self, name: str, detail: str | None = None) -> None:
        index = _STAGES.index(name) + 1
        suffix = f" · {detail}" if detail else ""
        self._console.print()
        self._console.rule(
            f"[bold cyan]Schritt {index}/{len(_STAGES)} · {name}{suffix}[/bold cyan]"
        )

    def _ask(self, actions: Sequence[_Action]) -> str:
        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column(justify="right", style="bold cyan", no_wrap=True)
        table.add_column(style="dim", no_wrap=True)
        table.add_column(style="bold", no_wrap=True)
        table.add_column(style="dim", overflow="fold")
        for index, action in enumerate(actions, start=1):
            table.add_row(str(index), f"({action.key})", action.label, action.description)
        self._console.print(
            Panel(
                table,
                title="[bold]Was möchtest du tun?[/bold]",
                title_align="left",
                border_style="cyan",
            )
        )
        lookup: dict[str, str] = {}
        for index, action in enumerate(actions, start=1):
            for token in (str(index), action.key, action.label.casefold(), *action.words):
                lookup.setdefault(token.casefold(), action.key)
        while True:
            raw = cast(str, typer.prompt("Auswahl", default="1")).strip().casefold()
            if raw in lookup:
                return lookup[raw]
            options = ", ".join(
                f"{index}/{action.key} = {action.label}"
                for index, action in enumerate(actions, start=1)
            )
            self._console.print(f"[red]Ungültige Eingabe.[/red] Möglich: {options}")

    def _instruction(self, hint: str) -> str:
        self._console.print(f"[dim]{hint}[/dim]")
        return cast(str, typer.prompt("Deine Anweisung"))

    def _work(self, message: str) -> Status:
        return self._console.status(f"[cyan]{message}[/cyan]", spinner="dots")

    def _done(self, message: str) -> None:
        self._console.print(f"[green]✓[/green] {message}")

    def _prompt_languages(self, default: str) -> list[str]:
        while True:
            raw = cast(str, typer.prompt("Sprachen (ISO 639-1, kommagetrennt)", default=default))
            languages = _parse_list(raw)
            if languages and all(re.fullmatch(r"[a-z]{2}", code) for code in languages):
                return languages
            self._console.print(
                "[red]Bitte 2-Buchstaben-Codes angeben[/red], z. B. [bold]en,th[/bold]."
            )

    def _prompt_spreads(self, default: int) -> int:
        while True:
            value = cast(int, typer.prompt("Anzahl Doppelseiten (1-30)", default=default, type=int))
            if 1 <= value <= 30:
                return value
            self._console.print("[red]Bitte einen Wert zwischen 1 und 30 wählen.[/red]")

    def _abort(self, slug: str | None = None) -> None:
        resume = f" Fortsetzen mit: kb assistant {slug}" if slug else ""
        raise AssistantAborted(f"Assistent pausiert; der aktuelle Stand ist gespeichert.{resume}")

    # ------------------------------------------------------------------ content views

    def _details(self, title: str, rows: Sequence[tuple[str, str]], border: str = "dim") -> None:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold", no_wrap=True)
        grid.add_column(overflow="fold")
        for label, value in rows:
            grid.add_row(label, escape(value) if value else "[dim]—[/dim]")
        self._console.print(Panel(grid, title=title, title_align="left", border_style=border))

    def _show_universe(self, universe: Universe) -> None:
        self._details(
            f"[bold]Universum · {escape(universe.name)}[/bold] [dim]({universe.slug})[/dim]",
            [
                ("Sprachen", ", ".join(universe.languages)),
                ("Beschreibung", universe.description),
                ("Illustrationsstil", universe.style_guide),
            ],
        )

    def _show_book(self, book: Book) -> None:
        self._details(
            f"[bold]Buchidee · {escape(book.title)}[/bold] [dim]({book.slug})[/dim]",
            [
                ("Idee", book.idea),
                ("Altersgruppe", book.age_group),
                ("Doppelseiten", str(book.spreads)),
                ("Sprachen", ", ".join(book.languages)),
            ],
        )

    def _show_outline(self, value: Outline) -> None:
        rows = [("Titel", value.title), ("Prämisse", value.premise)]
        rows += [
            (f"Seite {number}", synopsis)
            for number, synopsis in enumerate(value.page_synopses, start=1)
        ]
        self._details("[bold]Outline[/bold]", rows)

    def _show_story(self, value: Story) -> None:
        self._details(
            "[bold]Story[/bold]",
            [
                (f"Seite {number}", beat.narrative)
                for number, beat in enumerate(value.beats, start=1)
            ],
        )

    def _show_bible(self, book: Book) -> None:
        for character in book.characters:
            self._details(
                f"[bold]{escape(character.name)}[/bold] [dim]· {escape(character.role)}[/dim]",
                [
                    ("Beschreibung", character.description),
                    ("Merkmale", ", ".join(character.visual_keywords)),
                    ("Referenzbild", str(character.primary_reference or "")),
                ],
            )

    def _show_page(self, book: Book, number: int) -> None:
        page = editing.get_page(book, number)
        status_style = {
            "todo": "red",
            "text_done": "yellow",
            "image_done": "cyan",
            "approved": "green",
        }.get(page.status, "white")
        rows = [(lang, page.text.get(lang, "")) for lang in book.languages]
        rows.append(("Bildprompt", page.image_prompt or ""))
        rows.append(
            (
                "Bild",
                str(self._books.book_dir(book.slug) / page.image_path) if page.image_path else "",
            )
        )
        self._details(
            f"[bold]Doppelseite {number}[/bold] "
            f"[dim]· Status:[/dim] [{status_style}]{page.status}[/{status_style}]",
            rows,
        )


def _parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_slug(value: str) -> None:
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) is None:
        raise typer.BadParameter(f"Slug muss kebab-case sein, erhalten: {value!r}")
