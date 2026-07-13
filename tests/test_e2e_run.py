"""Gate 2 (spec §15): offline end-to-end pipeline run with both mock providers.

Zero network access, zero API cost. Covers HC-2.1, HC-4.1, and §7.3 resumability.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from kb.cli import app

runner = CliRunner()


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_LLM_PROVIDER", "mock")
    monkeypatch.setenv("KB_IMAGE_PROVIDER", "mock")


def _run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def _snapshot(root: Path) -> dict[str, tuple[float, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_gate2_full_offline_run(workspace: Path, mock_env: None) -> None:
    assert _run("book", "new", "demo", "--universe", "swiss-thai-myths")[0] == 0
    code, output = _run("run", "demo")
    assert code == 0, output

    book_dir = workspace / "Books" / "demo"
    book = yaml.safe_load((book_dir / "book.yaml").read_text("utf-8"))

    # Steps 01-02: structured artifacts exist (HC-1.1)
    assert book["outline"] is not None
    assert book["story"] is not None
    assert book["title"] == book["outline"]["title"]  # authored title adopted (Step 01)

    # Step 03: every character has exactly one primary reference image (HC-2.1)
    assert book["characters"]
    for character in book["characters"]:
        reference = character["primary_reference"]
        assert reference is not None
        assert (book_dir / reference).is_file()

    # Step 04: every page has text in every configured language + an image (HC-1.2)
    page_files = sorted((book_dir / "pages").glob("*.yaml"))
    assert len(page_files) == len(book["story"]["beats"])
    seen_texts: list[str] = []
    seen_images: list[bytes] = []
    for page_file in page_files:
        page = yaml.safe_load(page_file.read_text("utf-8"))
        assert set(page["text"]) == {"en", "th"}
        assert re.search(r"[\u0e00-\u0e7f]", page["text"]["th"])  # Thai script (HC-3.4 downstream)
        assert page["status"] == "image_done"
        assert (book_dir / page["image_path"]).is_file()
        seen_texts.append(page["text"]["en"])
        seen_images.append((book_dir / page["image_path"]).read_bytes())

    # every page and every picture must be different
    assert len(set(seen_texts)) == len(seen_texts)
    assert len({hash(i) for i in seen_images}) == len(seen_images)

    # Markdown views are generated, never sources (HC-1.3)
    assert (book_dir / "views" / "story.md").is_file()
    assert (book_dir / "views" / "bible.md").is_file()


def test_gate2_hc41_second_run_is_noop(workspace: Path, mock_env: None) -> None:
    _run("book", "new", "demo", "--universe", "swiss-thai-myths")
    assert _run("run", "demo")[0] == 0

    state_dir = workspace / "Books" / "demo"
    before = (
        _snapshot(state_dir / "pages")
        | _snapshot(state_dir / "images")
        | _snapshot(state_dir / "references")
    )
    code, output = _run("run", "demo")
    assert code == 0
    assert "nothing to do" in output
    after = (
        _snapshot(state_dir / "pages")
        | _snapshot(state_dir / "images")
        | _snapshot(state_dir / "references")
    )
    assert before == after  # byte-for-byte untouched (HC-4.1)


def test_gate2_interrupted_run_resumes(workspace: Path, mock_env: None) -> None:
    """Simulate an interruption after page 2's text: only missing work is redone."""
    _run("book", "new", "demo", "--universe", "swiss-thai-myths")
    assert _run("run", "demo")[0] == 0

    book_dir = workspace / "Books" / "demo"
    page_file = book_dir / "pages" / "002.yaml"
    page = yaml.safe_load(page_file.read_text("utf-8"))
    (book_dir / page["image_path"]).unlink()
    page["status"] = "text_done"
    page["image_path"] = None
    page_file.write_text(yaml.safe_dump(page, allow_unicode=True, sort_keys=False), "utf-8")

    untouched_before = _snapshot(book_dir / "images")
    untouched_before.pop("page-002.png", None)

    assert _run("run", "demo")[0] == 0

    restored = yaml.safe_load(page_file.read_text("utf-8"))
    assert restored["status"] == "image_done"
    assert (book_dir / restored["image_path"]).is_file()

    untouched_after = _snapshot(book_dir / "images")
    untouched_after.pop("page-002.png", None)
    assert untouched_before == untouched_after  # siblings untouched
