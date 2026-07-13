"""Minimal local web preview (spec §12) — a single-user editor aid, not a product.

Read-only: it renders book state and serves generated images. All mutation goes
through the CLI.
"""

from __future__ import annotations

import html
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

from kb.core.book_manager import BookManager
from kb.errors import NotFoundError

_STYLE = """
body { font-family: sans-serif; max-width: 60rem; margin: 2rem auto; padding: 0 1rem; }
img { max-width: 20rem; display: block; border: 1px solid #ccc; }
section { margin-bottom: 2rem; }
.status { color: #666; font-size: 0.9rem; }
"""


def create_app(books_dir: Path) -> FastAPI:
    app = FastAPI(title="kb preview", docs_url=None, redoc_url=None)
    manager = BookManager(books_dir)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        items = "".join(
            f'<li><a href="/books/{html.escape(slug)}">{html.escape(slug)}</a></li>'
            for slug in manager.list_slugs()
        )
        return (
            f"<html><head><style>{_STYLE}</style></head>"
            f"<body><h1>Books</h1><ul>{items}</ul></body></html>"
        )

    @app.get("/books/{slug}", response_class=HTMLResponse)
    def book_view(slug: str) -> str:
        try:
            book = manager.load(slug)
        except NotFoundError:
            return HTMLResponse(f"unknown book: {html.escape(slug)}", status_code=404)  # type: ignore[return-value]
        sections = []
        for page in book.pages:
            texts = "".join(
                f'<p lang="{html.escape(lang)}"><strong>{html.escape(lang)}:</strong> '
                f"{html.escape(text)}</p>"
                for lang, text in sorted(page.text.items())
            )
            image = (
                f'<img src="/books/{html.escape(slug)}/files/{html.escape(str(page.image_path))}">'
                if page.image_path
                else "<em>no image yet</em>"
            )
            sections.append(
                f"<section><h2>Page {page.number} "
                f'<span class="status">({html.escape(page.status)})</span></h2>'
                f"{texts}{image}</section>"
            )
        return (
            f"<html><head><style>{_STYLE}</style></head><body>"
            f"<h1>{html.escape(book.title)}</h1><p><a href='/'>&larr; all books</a></p>"
            f"{''.join(sections)}</body></html>"
        )

    @app.get("/books/{slug}/files/{file_path:path}")
    def book_file(slug: str, file_path: str) -> FileResponse:
        book_dir = manager.book_dir(slug).resolve()
        target = (book_dir / file_path).resolve()
        if not target.is_relative_to(book_dir) or not target.is_file():  # path traversal guard
            return HTMLResponse("not found", status_code=404)  # type: ignore[return-value]
        return FileResponse(target)

    return app
