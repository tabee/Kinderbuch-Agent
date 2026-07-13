"""Print-ready PDF rendering with WeasyPrint (spec §11, HC-3.x).

Geometry comes from a layout definition in ``Global/layouts/``; fonts are
embedded exclusively from ``Global/fonts/`` (HC-3.5). The HTML intermediate is
kept in ``build/`` for debugging (disposable, §6.3).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from kb.core.models import Book, Universe
from kb.core.persistence import atomic_write_text, read_yaml
from kb.errors import KBError

_REQUIRED_FONTS = (
    "NotoSans-Regular.ttf",
    "NotoSans-Bold.ttf",
    "NotoSansThai-Regular.ttf",
    "NotoSansThai-Bold.ttf",
)


class _TextPageMargins(BaseModel):
    gutter_margin_mm: float = 20
    outer_margin_mm: float = 12
    top_margin_mm: float = 12
    bottom_margin_mm: float = 12


class _Layout(BaseModel):
    """Layout definition, loaded from ``Global/layouts/<name>.yaml`` (spec §11.1)."""

    name: str = "default"
    trim_width_mm: float = 210
    trim_height_mm: float = 210
    bleed_mm: float = 3
    text_page: _TextPageMargins = _TextPageMargins()


def render_pdf(
    book: Book,
    universe: Universe,
    book_dir: Path,
    global_dir: Path,
    layout_name: str = "default",
) -> Path:
    """Render the book to ``build/<slug>.pdf`` and return the path."""
    _check_ready(book)
    fonts_dir = _check_fonts(global_dir / "fonts")
    layout = _load_layout(global_dir / "layouts" / f"{layout_name}.yaml")

    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    bleed = layout.bleed_mm
    margins = layout.text_page
    html = env.get_template("book.html.j2").render(
        book=book,
        universe=universe,
        fonts_dir=fonts_dir.resolve().as_uri(),
        page_w=layout.trim_width_mm + 2 * bleed,
        page_h=layout.trim_height_mm + 2 * bleed,
        text_font_size=_font_size_pt(book.age_group),
        m={
            "top": margins.top_margin_mm + bleed,
            "bottom": margins.bottom_margin_mm + bleed,
            "gutter": margins.gutter_margin_mm + bleed,
            "outer": margins.outer_margin_mm + bleed,
        },
    )

    build_dir = book_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(build_dir / f"{book.slug}.html", html)

    # WeasyPrint import is deferred: it needs Pango/cairo system libraries,
    # which only the PDF path requires (everything else stays importable).
    from weasyprint import HTML

    pdf_path = build_dir / f"{book.slug}.pdf"
    HTML(string=html, base_url=str(book_dir)).write_pdf(str(pdf_path))
    return pdf_path


def _font_size_pt(age_group: str) -> float:
    """Text-page font size by reading age: young readers get large type,
    young adults get book-sized type so bilingual spreads fit one page."""
    import re

    match = re.search(r"\d+", age_group)
    age = int(match.group()) if match else 5
    if age >= 12:
        return 9.5
    if age >= 7:
        return 12.0
    return 14.0


def _check_ready(book: Book) -> None:
    if not book.pages:
        raise KBError(f"book {book.slug!r} has no pages yet — run `kb run {book.slug}` first")
    missing = [p.number for p in book.pages if p.image_path is None]
    if missing:
        raise KBError(f"page(s) {missing} have no image yet — run `kb run {book.slug}` first")


def _check_fonts(fonts_dir: Path) -> Path:
    """All fonts must come from Global/fonts/ — no system fallback (HC-3.5)."""
    missing = [name for name in _REQUIRED_FONTS if not (fonts_dir / name).is_file()]
    if missing:
        raise KBError(
            f"missing font file(s) in {fonts_dir}: {', '.join(missing)} "
            "— see Global/fonts/README.md (HC-3.5)"
        )
    return fonts_dir


def _load_layout(path: Path) -> _Layout:
    if not path.is_file():
        raise KBError(f"unknown layout: {path}")
    return _Layout.model_validate(read_yaml(path))
