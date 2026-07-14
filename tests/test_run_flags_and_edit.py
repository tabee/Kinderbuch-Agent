"""Flag-semantics (§8.2, HC-4.2) and edit-lifecycle (§6.2) tests — offline, mock providers."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from kb.cli import app

runner = CliRunner()


@pytest.fixture
def demo(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fully pipelined book (mock providers); returns the book directory."""
    monkeypatch.setenv("KB_LLM_PROVIDER", "mock")
    monkeypatch.setenv("KB_IMAGE_PROVIDER", "mock")
    created = runner.invoke(app, ["book", "new", "demo", "--universe", "swiss-thai-myths"])
    assert created.exit_code == 0
    assert runner.invoke(app, ["run", "demo"]).exit_code == 0
    return workspace / "Books" / "demo"


def _page(book_dir: Path, number: int) -> dict[str, object]:
    return yaml.safe_load((book_dir / "pages" / f"{number:03d}.yaml").read_text("utf-8"))


def _write_page(book_dir: Path, number: int, page: dict[str, object]) -> None:
    (book_dir / "pages" / f"{number:03d}.yaml").write_text(
        yaml.safe_dump(page, allow_unicode=True, sort_keys=False), "utf-8"
    )


def _mtime(path: Path) -> int:
    return path.stat().st_mtime_ns


# ----------------------------------------------------------------- §8.2 flags


def test_pages_flag_restricts_work(demo: Path) -> None:
    """--recreate-images --pages 2 regenerates only page 2's image."""
    image_1 = demo / "images" / "page-001.png"
    image_2 = demo / "images" / "page-002.png"
    before_1, before_2 = _mtime(image_1), _mtime(image_2)

    result = runner.invoke(app, ["run", "demo", "--recreate-images", "--pages", "2"])
    assert result.exit_code == 0

    assert _mtime(image_1) == before_1  # untouched
    assert _mtime(image_2) > before_2  # regenerated


def test_from_page_and_pages_combine_by_intersection(demo: Path) -> None:
    """--from-page 3 --pages 1-3 selects only page 3 (§8.2)."""
    mtimes = {n: _mtime(demo / "images" / f"page-{n:03d}.png") for n in (1, 2, 3)}

    result = runner.invoke(
        app, ["run", "demo", "--recreate-images", "--from-page", "3", "--pages", "1-3"]
    )
    assert result.exit_code == 0

    assert _mtime(demo / "images" / "page-001.png") == mtimes[1]
    assert _mtime(demo / "images" / "page-002.png") == mtimes[2]
    assert _mtime(demo / "images" / "page-003.png") > mtimes[3]


def test_default_run_never_touches_approved_pages(demo: Path) -> None:
    page = _page(demo, 1)
    page["status"] = "approved"
    _write_page(demo, 1, page)

    # force page 1 to look image-less except approved status protects it
    result = runner.invoke(app, ["run", "demo"])
    assert result.exit_code == 0
    assert _page(demo, 1)["status"] == "approved"  # untouched (§8.2 default)


def test_recreate_images_revokes_approval(demo: Path) -> None:
    page = _page(demo, 1)
    page["status"] = "approved"
    _write_page(demo, 1, page)

    result = runner.invoke(app, ["run", "demo", "--recreate-images", "--pages", "1"])
    assert result.exit_code == 0
    assert _page(demo, 1)["status"] == "image_done"  # approval revoked (§8.2)


def test_force_regenerates_approved_pages(demo: Path) -> None:
    page = _page(demo, 1)
    page["status"] = "approved"
    _write_page(demo, 1, page)
    before = _mtime(demo / "images" / "page-001.png")

    result = runner.invoke(app, ["run", "demo", "--force", "--pages", "1"])
    assert result.exit_code == 0

    refreshed = _page(demo, 1)
    assert refreshed["status"] == "image_done"
    assert _mtime(demo / "images" / "page-001.png") > before


def test_recreate_images_keeps_texts(demo: Path) -> None:
    before_text = _page(demo, 1)["text"]

    result = runner.invoke(app, ["run", "demo", "--recreate-images"])
    assert result.exit_code == 0
    assert _page(demo, 1)["text"] == before_text  # texts kept (§8.2)


def test_recreate_images_redraws_reference_images(demo: Path) -> None:
    """Unrestricted --recreate-images regenerates character references too (§8.2)."""
    book = yaml.safe_load((demo / "book.yaml").read_text("utf-8"))
    references = [demo / c["primary_reference"] for c in book["characters"]]
    assert references
    before = {p: _mtime(p) for p in references}
    bible_text_before = [
        (c["name"], c["description"], c["visual_keywords"]) for c in book["characters"]
    ]

    result = runner.invoke(app, ["run", "demo", "--recreate-images"])
    assert result.exit_code == 0

    for path in references:
        assert _mtime(path) > before[path]  # every reference redrawn
    book_after = yaml.safe_load((demo / "book.yaml").read_text("utf-8"))
    bible_text_after = [
        (c["name"], c["description"], c["visual_keywords"]) for c in book_after["characters"]
    ]
    assert bible_text_after == bible_text_before  # bible TEXT untouched


def test_page_restricted_recreate_images_keeps_references(demo: Path) -> None:
    """--recreate-images --pages N regenerates only that page image (§8.2)."""
    book = yaml.safe_load((demo / "book.yaml").read_text("utf-8"))
    references = [demo / c["primary_reference"] for c in book["characters"]]
    before = {p: _mtime(p) for p in references}

    result = runner.invoke(app, ["run", "demo", "--recreate-images", "--pages", "1"])
    assert result.exit_code == 0

    for path in references:
        assert _mtime(path) == before[path]  # references untouched


def test_interactive_abort_exits_one(demo: Path) -> None:
    """--interactive with a declined confirmation aborts the run (§8.2)."""
    result = runner.invoke(app, ["run", "demo", "--force", "--interactive"], input="n\n")
    assert result.exit_code == 1
    assert "aborted" in result.output


def test_safety_refusal_reports_page_and_edit_command(
    demo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A content-safety refusal names the page and the exact kb edit fix (§7.3)."""
    from collections.abc import Sequence

    from kb.errors import ImageSafetyError
    from kb.image.mock import MockImageProvider

    class SafetyBlockedProvider(MockImageProvider):
        async def _generate(
            self, *, prompt: str, out_path: Path, references: Sequence[Path], size: int
        ) -> Path:
            if "page-002" in out_path.name:
                raise ImageSafetyError(
                    "the provider's content-safety filter refused this image (IMAGE_SAFETY)"
                )
            return await super()._generate(
                prompt=prompt, out_path=out_path, references=references, size=size
            )

    monkeypatch.setattr("kb.cli.create_image_provider", lambda settings: SafetyBlockedProvider())

    result = runner.invoke(app, ["run", "demo", "--recreate-images"])

    assert result.exit_code == 1
    assert "REFUSED" in result.output
    assert "content-safety filter" in result.output
    assert "retrying will not help" in result.output
    assert "kb edit demo --page 2 --image" in result.output
    # non-safety pages still regenerated fine and are not blamed
    assert "page(s) 2" in result.output


# ----------------------------------------------------------------- §6.2 edits


def test_text_edit_updates_and_revokes_approval(demo: Path) -> None:
    page = _page(demo, 1)
    page["status"] = "approved"
    _write_page(demo, 1, page)

    result = runner.invoke(
        app, ["edit", "demo", "--page", "1", "--text-en", "New sentence.", "--text-th", "ประโยคใหม่"]
    )
    assert result.exit_code == 0

    updated = _page(demo, 1)
    assert updated["text"]["en"] == "New sentence."
    assert updated["text"]["th"] == "ประโยคใหม่"
    assert updated["status"] == "image_done"  # image exists → image_done (§6.2)


def test_image_edit_appends_instruction_and_revokes_approval(demo: Path) -> None:
    page = _page(demo, 1)
    page["status"] = "approved"
    _write_page(demo, 1, page)
    before = _mtime(demo / "images" / "page-001.png")

    result = runner.invoke(app, ["edit", "demo", "--page", "1", "--image", "make it happier"])
    assert result.exit_code == 0

    updated = _page(demo, 1)
    assert "Edit: make it happier" in str(updated["image_prompt"])  # appended (§6.2)
    assert updated["status"] == "image_done"
    assert _mtime(demo / "images" / "page-001.png") > before


def test_image_prompt_edit_replaces_prompt_entirely(demo: Path) -> None:
    """--image-prompt is the safety-refusal escape hatch: full prompt replacement."""
    before = _mtime(demo / "images" / "page-001.png")

    result = runner.invoke(
        app, ["edit", "demo", "--page", "1", "--image-prompt", "A calm meadow at sunrise."]
    )
    assert result.exit_code == 0

    updated = _page(demo, 1)
    assert updated["image_prompt"] == "A calm meadow at sunrise."  # replaced, not appended
    assert updated["status"] == "image_done"
    assert _mtime(demo / "images" / "page-001.png") > before


def test_image_and_image_prompt_are_mutually_exclusive(demo: Path) -> None:
    result = runner.invoke(
        app,
        ["edit", "demo", "--page", "1", "--image", "x", "--image-prompt", "y"],
    )
    assert result.exit_code == 2


def test_approve_page_requires_image_done(demo: Path) -> None:
    assert runner.invoke(app, ["edit", "demo", "--approve-page", "1"]).exit_code == 0
    assert _page(demo, 1)["status"] == "approved"

    # approving an already-approved page is an error (§6.2: image_done → approved only)
    result = runner.invoke(app, ["edit", "demo", "--approve-page", "1"])
    assert result.exit_code == 1
    assert "image_done" in result.output


def test_bible_edit_keeps_reference_images_for_unchanged_slugs(demo: Path) -> None:
    book_before = yaml.safe_load((demo / "book.yaml").read_text("utf-8"))
    references_before = {c["slug"]: c["primary_reference"] for c in book_before["characters"]}

    result = runner.invoke(app, ["edit", "demo", "--bible", "make everyone friendlier"])
    assert result.exit_code == 0

    book_after = yaml.safe_load((demo / "book.yaml").read_text("utf-8"))
    for character in book_after["characters"]:
        if character["slug"] in references_before:
            assert character["primary_reference"] == references_before[character["slug"]]


def test_edit_without_operation_is_usage_error(demo: Path) -> None:
    assert runner.invoke(app, ["edit", "demo"]).exit_code == 2


def test_edit_text_without_page_is_usage_error(demo: Path) -> None:
    assert runner.invoke(app, ["edit", "demo", "--text-en", "x"]).exit_code == 2


def test_llm_text_rewrite_updates_all_languages_and_revokes_approval(demo: Path) -> None:
    """kb edit --text 'instruction' rewrites via LLM in every language (§6.2)."""
    page = _page(demo, 1)
    page["status"] = "approved"
    before_text = dict(page["text"])  # type: ignore[arg-type]
    _write_page(demo, 1, page)

    result = runner.invoke(app, ["edit", "demo", "--page", "1", "--text", "make it shorter"])
    assert result.exit_code == 0

    updated = _page(demo, 1)
    assert set(updated["text"]) == {"en", "th"}  # type: ignore[arg-type]
    assert updated["text"] != before_text
    assert updated["status"] == "image_done"  # approval revoked (§6.2)


def test_book_show_page_displays_text_and_prompt(demo: Path) -> None:
    result = runner.invoke(app, ["book", "show", "demo", "--page", "1"])
    assert result.exit_code == 0
    page = _page(demo, 1)
    text = page["text"]["en"][:30]  # type: ignore[index]
    assert text in result.output.replace("\n", " ") or text.split()[0] in result.output
    assert "image prompt" in result.output


def test_book_show_unknown_page_is_usage_error(demo: Path) -> None:
    assert runner.invoke(app, ["book", "show", "demo", "--page", "99"]).exit_code == 2
