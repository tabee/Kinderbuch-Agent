"""Web preview tests (spec §12) — offline, read-only."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kb.cli import app as cli_app
from kb.web.app import create_app

runner = CliRunner()


@pytest.fixture
def client(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KB_LLM_PROVIDER", "mock")
    monkeypatch.setenv("KB_IMAGE_PROVIDER", "mock")
    created = runner.invoke(cli_app, ["book", "new", "demo", "--universe", "swiss-thai-myths"])
    assert created.exit_code == 0
    assert runner.invoke(cli_app, ["run", "demo"]).exit_code == 0
    return TestClient(create_app(workspace / "Books"))


def test_index_lists_books(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "demo" in response.text


def test_book_view_shows_pages_and_both_languages(client: TestClient) -> None:
    response = client.get("/books/demo")
    assert response.status_code == 200
    assert "Page 1" in response.text
    assert 'lang="th"' in response.text


def test_book_file_serves_images(client: TestClient) -> None:
    response = client.get("/books/demo/files/images/page-001.png")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


def test_unknown_book_404(client: TestClient) -> None:
    assert client.get("/books/nope").status_code == 404


def test_path_traversal_is_blocked(client: TestClient) -> None:
    assert client.get("/books/demo/files/../../../etc/passwd").status_code == 404
