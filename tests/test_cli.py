"""CLI surface and exit-code tests (spec §8, §13)."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from kb.cli import app

runner = CliRunner()


def test_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("universe", "book", "run", "edit", "pdf", "serve", "open"):
        assert command in result.output


def test_book_new_inherits_universe_languages(workspace: Path) -> None:
    result = runner.invoke(app, ["book", "new", "demo", "--universe", "swiss-thai-myths"])
    assert result.exit_code == 0

    data = yaml.safe_load((workspace / "Books" / "demo" / "book.yaml").read_text("utf-8"))
    assert data["languages"] == ["en", "th"]
    assert data["universe_slug"] == "swiss-thai-myths"


def test_book_new_langs_override(workspace: Path) -> None:
    result = runner.invoke(
        app, ["book", "new", "demo", "--universe", "swiss-thai-myths", "--langs", "en"]
    )
    assert result.exit_code == 0

    data = yaml.safe_load((workspace / "Books" / "demo" / "book.yaml").read_text("utf-8"))
    assert data["languages"] == ["en"]


def test_book_new_unknown_universe_is_usage_error(workspace: Path) -> None:
    result = runner.invoke(app, ["book", "new", "demo", "--universe", "nope"])
    assert result.exit_code == 2


def test_book_new_duplicate_is_usage_error(workspace: Path) -> None:
    assert (
        runner.invoke(app, ["book", "new", "demo", "--universe", "swiss-thai-myths"]).exit_code == 0
    )
    result = runner.invoke(app, ["book", "new", "demo", "--universe", "swiss-thai-myths"])
    assert result.exit_code == 2


def test_run_unknown_book_is_usage_error(workspace: Path) -> None:
    result = runner.invoke(app, ["run", "nope"])
    assert result.exit_code == 2


def test_run_invalid_pages_spec_is_usage_error(workspace: Path) -> None:
    runner.invoke(app, ["book", "new", "demo", "--universe", "swiss-thai-myths"])
    result = runner.invoke(app, ["run", "demo", "--pages", "5-3"])
    assert result.exit_code == 2


def test_run_without_credentials_fails_cleanly(workspace: Path) -> None:
    """Default provider is anthropic; without a key the run must fail fast (HC-5.3)."""
    runner.invoke(app, ["book", "new", "demo", "--universe", "swiss-thai-myths"])
    result = runner.invoke(app, ["run", "demo"])
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_universe_list_shows_universe(workspace: Path) -> None:
    result = runner.invoke(app, ["universe", "list"])
    assert result.exit_code == 0
    assert "swiss-thai-myths" in result.output


def test_book_status(workspace: Path) -> None:
    runner.invoke(app, ["book", "new", "demo", "--universe", "swiss-thai-myths"])
    result = runner.invoke(app, ["book", "status", "demo"])
    assert result.exit_code == 0
    assert "Demo" in result.output
