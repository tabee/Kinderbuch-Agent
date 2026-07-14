"""Guided assistant workflow tests with both providers mocked offline."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from kb.cli import app
from kb.core import editing
from kb.core.book_manager import BookManager
from kb.core.models import Outline

runner = CliRunner()

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


def test_assistant_pauses_resumes_reviews_and_renders_pdf(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guide persists a pause, accepts an LLM revision, and resumes to PDF."""
    monkeypatch.setenv("KB_LLM_PROVIDER", "mock")
    monkeypatch.setenv("KB_IMAGE_PROVIDER", "mock")
    _install_pdf_assets(workspace)

    first_run = runner.invoke(
        app,
        ["assistant"],
        input=(
            "swiss-thai-myths\n"
            "a\n"
            "demo\n"
            "Guided Demo\n"
            "A child connects two mountain homes.\n"
            "\n"
            "3\n"
            "a\n"
            "l\n"
            "Make every spread more playful.\n"
            "a\n"
            "q\n"
        ),
    )
    assert first_run.exit_code == 0, first_run.output
    assert "Fortsetzen mit: kb" in first_run.output
    assert "assistant demo" in first_run.output
    book_file = workspace / "Books" / "demo" / "book.yaml"
    paused = yaml.safe_load(book_file.read_text("utf-8"))
    assert paused["outline"] is not None
    assert paused["story"] is not None
    assert paused["characters"] == []

    resumed = runner.invoke(
        app,
        ["assistant", "demo"],
        input="a\na\na\na\na\na\na\na\n",
    )
    assert resumed.exit_code == 0, resumed.output
    assert "Assistent abgeschlossen" in resumed.output

    page_files = sorted((workspace / "Books" / "demo" / "pages").glob("*.yaml"))
    assert len(page_files) == 3
    assert all(
        yaml.safe_load(path.read_text("utf-8"))["status"] == "approved" for path in page_files
    )
    assert (workspace / "Books" / "demo" / "build" / "demo.pdf").is_file()


def test_outline_revision_removes_stale_downstream_artifacts(workspace: Path) -> None:
    runner.invoke(app, ["book", "new", "demo", "--universe", "swiss-thai-myths"])
    manager = BookManager(workspace / "Books")
    book = manager.load("demo")
    book_dir = workspace / "Books" / "demo"
    stale_paths = [
        book_dir / "pages" / "001.yaml",
        book_dir / "images" / "page-001.png",
        book_dir / "references" / "hero.png",
        book_dir / "views" / "story.md",
        book_dir / "views" / "bible.md",
        book_dir / "build" / "demo.html",
        book_dir / "build" / "demo.pdf",
    ]
    for path in stale_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale", encoding="utf-8")

    editing.replace_outline(
        manager,
        book,
        Outline(
            title="Fresh",
            premise="A new premise.",
            page_synopses=[f"Beat {number}" for number in range(1, 6)],
        ),
    )

    assert all(not path.exists() for path in stale_paths)


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
