"""Web editor tests (spec §12): feature parity with `kb assistant`, offline.

Every mutating LLM/image action runs through a background job (see
``kb.web.jobs``); tests poll ``app.state.jobs`` until the job is done instead of
sleeping blindly. Both providers are mocked — zero network, zero API cost.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kb.core.book_manager import BookManager
from kb.web.app import create_app
from kb.web.jobs import Job

_FONTS = (
    "NotoSans-Regular.ttf",
    "NotoSans-Bold.ttf",
    "NotoSansThai-Regular.ttf",
    "NotoSansThai-Bold.ttf",
)
_PROJECT_ROOT = Path(__file__).parent.parent
_REAL_FONTS_DIR = _PROJECT_ROOT / "Global" / "fonts"

pytestmark = pytest.mark.skipif(
    not all((_REAL_FONTS_DIR / name).is_file() for name in _FONTS),
    reason="Noto fonts not downloaded into Global/fonts/",
)


def _install_pdf_assets(workspace: Path) -> None:
    fonts_dir = workspace / "Global" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for name in _FONTS:
        shutil.copy(_REAL_FONTS_DIR / name, fonts_dir / name)
    layouts_dir = workspace / "Global" / "layouts"
    layouts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        _PROJECT_ROOT / "Global" / "layouts" / "default.yaml",
        layouts_dir / "default.yaml",
    )


@pytest.fixture
def app_client(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, TestClient]:
    monkeypatch.setenv("KB_LLM_PROVIDER", "mock")
    monkeypatch.setenv("KB_IMAGE_PROVIDER", "mock")
    app = create_app(workspace)
    return app, TestClient(app)


def _wait_for_job(app: FastAPI, timeout: float = 5.0) -> Job:
    """Poll the single-slot job runner until the in-flight job completes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = app.state.jobs.current
        if job is not None and job.done:
            return job
        time.sleep(0.01)
    raise AssertionError("background job did not finish in time")


def _generate(app: FastAPI, client: TestClient, slug: str) -> None:
    response = client.post(f"/books/{slug}/generate", follow_redirects=False)
    assert response.status_code == 303, response.text
    job = _wait_for_job(app)
    assert job.error is None, job.error


def _create_book(client: TestClient, slug: str, spreads: int = 3) -> None:
    response = client.post(
        "/books/new",
        data={
            "slug": slug,
            "universe_slug": "swiss-thai-myths",
            "title": "",
            "idea": "A child connects two mountain homes.",
            "age_group": "4-6",
            "spreads": spreads,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"/books/{slug}?ok=Buch+angelegt."


# --------------------------------------------------------------------------- universes


def test_create_universe_via_web_form(app_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_client
    response = client.post(
        "/universes/new",
        data={
            "slug": "duesterwald",
            "name": "Düsterwald",
            "languages": "de,en",
            "description": "A dark, spooky forest.",
            "style_guide": "black and white manga",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/universes/duesterwald?ok=Universum+angelegt."

    page = client.get("/universes/duesterwald")
    assert page.status_code == 200
    assert "Düsterwald" in page.text


def test_universe_new_rejects_bad_slug(app_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_client
    response = client.post(
        "/universes/new",
        data={"slug": "Not A Slug!", "languages": "en,th"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "err=" in response.headers["location"]


def test_universe_manual_edit_persists(
    app_client: tuple[FastAPI, TestClient], workspace: Path
) -> None:
    _, client = app_client
    response = client.post(
        "/universes/swiss-thai-myths/edit",
        data={
            "name": "Swiss-Thai Myths Revised",
            "languages": "en, th",
            "description": "Updated description.",
            "style_guide": "Updated style.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = yaml.safe_load(
        (workspace / "Global" / "universes" / "swiss-thai-myths" / "universe.yaml").read_text(
            "utf-8"
        )
    )
    assert saved["name"] == "Swiss-Thai Myths Revised"
    assert saved["description"] == "Updated description."


def test_universe_llm_revise_via_job(
    app_client: tuple[FastAPI, TestClient], workspace: Path
) -> None:
    app, client = app_client
    response = client.post(
        "/universes/swiss-thai-myths/revise",
        data={"instruction": "make it darker and more mysterious"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    job = _wait_for_job(app)
    assert job.error is None
    saved = yaml.safe_load(
        (workspace / "Global" / "universes" / "swiss-thai-myths" / "universe.yaml").read_text(
            "utf-8"
        )
    )
    assert saved["description"] != "Alpine folklore meets Thai mythology."


# --------------------------------------------------------------------------- books


def test_create_book_via_web_form(app_client: tuple[FastAPI, TestClient], workspace: Path) -> None:
    _, client = app_client
    _create_book(client, "demo")
    book = BookManager(workspace / "Books").load("demo")
    assert book.universe_slug == "swiss-thai-myths"
    assert book.languages == ["en", "th"]  # inherited from the universe
    assert book.idea == "A child connects two mountain homes."


def test_book_new_rejects_duplicate_slug(app_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_client
    _create_book(client, "demo")
    response = client.post(
        "/books/new",
        data={"slug": "demo", "universe_slug": "swiss-thai-myths"},
        follow_redirects=False,
    )
    assert "err=" in response.headers["location"]


def test_dashboard_shows_book_progress_badge(app_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_client
    _create_book(client, "demo")
    page = client.get("/")
    assert page.status_code == 200
    assert "demo" in page.text
    assert "Outline" in page.text  # next stage badge, no provider constructed


# --------------------------------------------------------------------------- full pipeline


def test_full_pipeline_via_web_reaches_pdf(
    app_client: tuple[FastAPI, TestClient], workspace: Path
) -> None:
    """The web editor alone drives a book from creation to a rendered PDF (§12)."""
    app, client = app_client
    _install_pdf_assets(workspace)
    _create_book(client, "demo", spreads=3)

    for _ in range(4):  # outline -> story -> bible(+refs) -> pages
        _generate(app, client, "demo")

    books = BookManager(workspace / "Books")
    book = books.load("demo")
    assert book.outline is not None
    assert book.story is not None
    assert len(book.characters) == 3
    assert all(c.primary_reference is not None for c in book.characters)
    assert len(book.pages) == 3
    assert all(p.status == "image_done" for p in book.pages)

    for page in book.pages:
        response = client.post(f"/books/demo/pages/{page.number}/approve", follow_redirects=False)
        assert response.status_code == 303
        assert "err=" not in response.headers["location"]

    response = client.post("/books/demo/pdf", follow_redirects=False)
    assert response.status_code == 303
    assert "err=" not in response.headers["location"]
    assert (workspace / "Books" / "demo" / "build" / "demo.pdf").is_file()

    book_page = client.get("/books/demo")
    assert 'lang="th"' in book_page.text  # Thai text rendered (HC-3.4 relevant content)


# --------------------------------------------------------------------------- page edits


@pytest.fixture
def book_at_pages_stage(app_client: tuple[FastAPI, TestClient]) -> tuple[FastAPI, TestClient, str]:
    app, client = app_client
    _create_book(client, "demo", spreads=3)
    for _ in range(4):
        _generate(app, client, "demo")
    return app, client, "demo"


def test_page_manual_text_edit_revokes_approval(
    book_at_pages_stage: tuple[FastAPI, TestClient, str], workspace: Path
) -> None:
    _, client, slug = book_at_pages_stage
    client.post(f"/books/{slug}/pages/1/approve", follow_redirects=False)

    response = client.post(
        f"/books/{slug}/pages/1/text",
        data={"text_en": "A brand new sentence.", "text_th": "ประโยคใหม่"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "err=" not in response.headers["location"]

    page = BookManager(workspace / "Books").load(slug).pages[0]
    assert page.text["en"] == "A brand new sentence."
    assert page.status == "image_done"  # approval revoked (§6.2)


def test_page_llm_rewrite_via_job(
    book_at_pages_stage: tuple[FastAPI, TestClient, str], workspace: Path
) -> None:
    app, client, slug = book_at_pages_stage
    books = BookManager(workspace / "Books")
    original = books.load(slug).pages[0].text["en"]

    response = client.post(
        f"/books/{slug}/pages/1/rewrite",
        data={"instruction": "shorter and funnier"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    job = _wait_for_job(app)
    assert job.error is None

    page = books.load(slug).pages[0]
    assert page.text["en"] != original


def test_page_image_edit_appends_instruction_via_job(
    book_at_pages_stage: tuple[FastAPI, TestClient, str], workspace: Path
) -> None:
    app, client, slug = book_at_pages_stage
    books = BookManager(workspace / "Books")
    original_prompt = books.load(slug).pages[0].image_prompt

    response = client.post(
        f"/books/{slug}/pages/1/image",
        data={"instruction": "more snow, warm evening light"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    job = _wait_for_job(app)
    assert job.error is None

    page = books.load(slug).pages[0]
    assert page.image_prompt is not None and original_prompt is not None
    assert page.image_prompt.startswith(original_prompt)
    assert "more snow, warm evening light" in page.image_prompt


def test_page_image_prompt_replace_via_job(
    book_at_pages_stage: tuple[FastAPI, TestClient, str], workspace: Path
) -> None:
    app, client, slug = book_at_pages_stage
    books = BookManager(workspace / "Books")
    original_prompt = books.load(slug).pages[0].image_prompt

    response = client.post(
        f"/books/{slug}/pages/1/image-prompt",
        data={"instruction": "a calmer scene by the lake, no storm"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    job = _wait_for_job(app)
    assert job.error is None

    page = books.load(slug).pages[0]
    assert page.image_prompt != original_prompt


def test_bible_edit_manual_redraws_references(
    book_at_pages_stage: tuple[FastAPI, TestClient, str], workspace: Path
) -> None:
    app, client, slug = book_at_pages_stage
    books = BookManager(workspace / "Books")
    character = books.load(slug).characters[0]

    response = client.post(
        f"/books/{slug}/bible/edit",
        data={
            "name_1": "Heidi the Renamed",
            "role_1": character.role,
            "description_1": character.description,
            "keywords_1": "red scarf, ash-grey fur",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    job = _wait_for_job(app)
    assert job.error is None

    revised = books.load(slug).characters[0]
    assert revised.name == "Heidi the Renamed"
    assert revised.visual_keywords == ["red scarf", "ash-grey fur"]


# --------------------------------------------------------------------------- security


def test_cross_origin_post_is_blocked(book_at_pages_stage: tuple[FastAPI, TestClient, str]) -> None:
    _, client, slug = book_at_pages_stage
    response = client.post(
        f"/books/{slug}/pages/1/approve",
        headers={"origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_temperature_next_url_is_sanitized(app_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_client
    response = client.post(
        "/settings/temperature",
        data={"temperature": "0.4", "next_url": "//evil.example/steal"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/?") or location == "/"
    assert "evil.example" not in location
