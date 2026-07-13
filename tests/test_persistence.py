"""Persistence and domain-model tests (HC-4.3/4.4, spec §6, §13)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from kb.core.book_manager import BookManager
from kb.core.models import Book, Page, Universe
from kb.core.persistence import atomic_write_yaml, read_yaml
from kb.errors import KBError, NotFoundError

UNIVERSE = Universe(slug="u", name="U", languages=["en", "th"])


def test_book_yaml_round_trip(tmp_path: Path) -> None:
    """Book/Page → YAML → Book/Page survives unchanged, including Thai text."""
    manager = BookManager(tmp_path / "Books")
    book = manager.create("demo", UNIVERSE)
    book.pages.append(
        Page(
            number=1,
            text={"en": "Hello mountain!", "th": "สวัสดีภูเขา!"},
            image_prompt="a friendly mountain",
            image_path=Path("images/page-001.png"),
            characters_present=["anna"],
            status="text_done",
        )
    )
    manager.save(book)

    assert manager.load("demo") == book


def test_hc44_no_temp_files_left_behind(tmp_path: Path) -> None:
    manager = BookManager(tmp_path / "Books")
    book = manager.create("demo", UNIVERSE)
    book.pages.append(Page(number=1))
    manager.save(book)

    assert not list((tmp_path / "Books").rglob("*.tmp"))


def test_newer_schema_version_is_rejected(tmp_path: Path) -> None:
    manager = BookManager(tmp_path / "Books")
    manager.create("demo", UNIVERSE)
    book_file = tmp_path / "Books" / "demo" / "book.yaml"
    data = read_yaml(book_file)
    data["schema_version"] = 99
    atomic_write_yaml(book_file, data)

    with pytest.raises(KBError, match="schema_version 99"):
        manager.load("demo")


def test_unknown_book_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError, match="unknown book"):
        BookManager(tmp_path / "Books").load("nope")


def test_languages_inherited_by_copy_not_reference(tmp_path: Path) -> None:
    """§6.1: languages are copied from the Universe and independent afterwards."""
    universe = Universe(slug="u", name="U", languages=["en", "th"])
    book = BookManager(tmp_path / "Books").create("demo", universe)

    universe.languages.append("de")

    assert book.languages == ["en", "th"]


def test_languages_override_at_creation(tmp_path: Path) -> None:
    book = BookManager(tmp_path / "Books").create("demo", UNIVERSE, languages=["en"])
    assert book.languages == ["en"]


def test_hc12_invalid_language_code_rejected() -> None:
    with pytest.raises(ValidationError, match="ISO 639-1"):
        Book(slug="x", title="X", universe_slug="u", languages=["english"])
