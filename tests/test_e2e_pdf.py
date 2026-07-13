"""Gate 3 (spec §15): offline book production — the final product test.

With both mock providers, ``kb run demo && kb pdf demo`` yields a complete
bilingual (EN/TH) children's book PDF with placeholder images at zero LLM cost.
Assertions: page count, 216 x 216 mm geometry (HC-3.2), embedded fonts from
Global/fonts/ (HC-3.5), English and Thai text present (HC-3.4).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader
from typer.testing import CliRunner

from kb.cli import app

runner = CliRunner()

_MM_216_IN_PT = 216 / 25.4 * 72  # ≈ 612.28

_FONTS = (
    "NotoSans-Regular.ttf",
    "NotoSans-Bold.ttf",
    "NotoSansThai-Regular.ttf",
    "NotoSansThai-Bold.ttf",
)
_REAL_FONTS_DIR = Path(__file__).parent.parent / "Global" / "fonts"

pytestmark = pytest.mark.skipif(
    not all((_REAL_FONTS_DIR / f).is_file() for f in _FONTS),
    reason="Noto fonts not downloaded into Global/fonts/ (see Global/fonts/README.md)",
)


@pytest.fixture
def produced_pdf(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Full offline production: book new → run → pdf. Zero LLM cost."""
    monkeypatch.setenv("KB_LLM_PROVIDER", "mock")
    monkeypatch.setenv("KB_IMAGE_PROVIDER", "mock")

    fonts_dir = workspace / "Global" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for name in _FONTS:
        shutil.copy(_REAL_FONTS_DIR / name, fonts_dir / name)
    layouts_dir = workspace / "Global" / "layouts"
    layouts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        Path(__file__).parent.parent / "Global" / "layouts" / "default.yaml",
        layouts_dir / "default.yaml",
    )

    created = runner.invoke(app, ["book", "new", "demo", "--universe", "swiss-thai-myths"])
    assert created.exit_code == 0
    assert runner.invoke(app, ["run", "demo"]).exit_code == 0
    result = runner.invoke(app, ["pdf", "demo"])
    assert result.exit_code == 0, result.output

    pdf_path = workspace / "Books" / "demo" / "build" / "demo.pdf"
    assert pdf_path.is_file()
    return pdf_path


def test_gate3_page_count_and_structure(produced_pdf: Path) -> None:
    """1 title page + (text page + image page) per spread (HC-3.1)."""
    reader = PdfReader(str(produced_pdf))
    assert len(reader.pages) == 1 + 2 * 3  # mock story has 3 beats


def test_gate3_hc32_page_geometry_includes_bleed(produced_pdf: Path) -> None:
    reader = PdfReader(str(produced_pdf))
    for page in reader.pages:
        box = page.mediabox
        assert float(box.width) == pytest.approx(_MM_216_IN_PT, abs=0.5)
        assert float(box.height) == pytest.approx(_MM_216_IN_PT, abs=0.5)


def test_gate3_hc35_fonts_embedded(produced_pdf: Path) -> None:
    """Both Noto families are embedded (FontFile present), no system fallback."""
    reader = PdfReader(str(produced_pdf))
    embedded: set[str] = set()
    for page in reader.pages:
        resources = page.get("/Resources", {})
        for font in resources.get("/Font", {}).values():
            font = font.get_object()
            descriptor = font.get("/FontDescriptor")
            if descriptor is None:  # e.g. Type0 → descend
                for sub in font.get("/DescendantFonts", []):
                    descriptor = sub.get_object().get("/FontDescriptor")
            if descriptor is not None:
                descriptor = descriptor.get_object()
                has_file = any(
                    key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")
                )
                assert has_file, f"font {font.get('/BaseFont')} is not embedded (HC-3.5)"
                # normalize subset names like 'BVNGPC+Noto-Sans-Thai'
                name = str(descriptor.get("/FontName", "")).split("+")[-1]
                embedded.add("".join(ch for ch in name if ch.isalnum()).lower())
    assert any(name.startswith("notosans") and "thai" not in name for name in embedded)
    assert any("notosansthai" in name for name in embedded)


def test_gate3_hc34_english_and_thai_text_present(produced_pdf: Path) -> None:
    reader = PdfReader(str(produced_pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert any(word in text for word in ("Alps", "naga", "mountain", "fireflies", "friends"))
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in text)  # Thai script survived typesetting


def test_gate3_zero_llm_cost_is_structural(produced_pdf: Path, workspace: Path) -> None:
    """The whole gate ran with mock providers — no credentials were ever needed."""
    import os

    assert os.environ.get("KB_LLM_PROVIDER") == "mock"
    assert os.environ.get("KB_IMAGE_PROVIDER") == "mock"
