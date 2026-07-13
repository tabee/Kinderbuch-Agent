# Kinderbuch Agent

`kb` turns an idea into a bilingual (EN/TH) illustrated children's book as a print-ready PDF: outline → story → character bible → pages → PDF, via an idempotent, resumable pipeline.

The authoritative specification is [implementation-spec.md](implementation-spec.md).

## Status

| Phase | State | Gate |
|---|---|---|
| 1 — Foundation | ✅ complete | quality gates + Docker image validated (kb, WeasyPrint, libthai, Pango) |
| 2 — Pipeline Core | ✅ complete | Gate 2: offline `kb run` e2e, idempotency, resume ([tests/test_e2e_run.py](tests/test_e2e_run.py)) |
| 3 — Output (PDF + preview) | ✅ complete | Gate 3: offline `kb run && kb pdf` → bilingual EN/TH PDF, zero LLM cost ([tests/test_e2e_pdf.py](tests/test_e2e_pdf.py)) |
| 4 — Hardening (Google images, polish) | ✅ complete | Gate 4: full §13 suite; real provider config-selectable, never exercised by tests |

All pipeline steps (outline → story → character bible → pages) run with structured LLM outputs, visual-consistency reference management, and parallel image generation. `kb pdf` produces a print-ready PDF: 216 × 216 mm pages (3 mm bleed), verso text / recto full-bleed image spreads, embedded Noto fonts, libthai-backed Thai line breaking. `Books/demo` is a complete offline example book.

## Quickstart

### Local (uv)

```bash
uv sync
uv run kb --help
```

### Docker

```bash
cp .env.example .env          # fill in ANTHROPIC_API_KEY for real LLM use
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml exec app kb --help
```

`./Books` and `./Global` are bind-mounted — generated files appear on the host immediately.

## First book in under 5 minutes

```bash
kb universe list                                            # ships with swiss-thai-myths
kb book new demo --universe swiss-thai-myths --langs en,th
kb run demo                # full pipeline; use KB_LLM_PROVIDER=mock for a free dry run
kb pdf demo                # → Books/demo/build/demo.pdf (print-ready)
kb serve                   # web preview at http://127.0.0.1:8000
kb open demo               # open the book in the preview
kb book status demo
```

Editing:

```bash
kb edit demo --page 2 --text-en "..." --text-th "..."   # revokes approval (§6.2)
kb edit demo --page 2 --image "make the child happier"  # regenerates that image
kb edit demo --bible "give the naga a red scarf"
kb edit demo --approve-page 2
kb run demo --recreate-images --pages 3,5-7             # selective regeneration
```

## Configuration

All configuration is via environment variables (`.env` supported locally); see [.env.example](.env.example) for the full annotated list. Provider credentials are only ever read inside the concrete provider classes.

**Real generation** (both providers verified live):

```bash
ANTHROPIC_API_KEY=...       # https://console.anthropic.com
GOOGLE_API_KEY=...          # https://aistudio.google.com/apikey
KB_IMAGE_PROVIDER=imagen    # Gemini image models with reference-image conditioning
KB_IMAGE_MODEL=             # default gemini-3.1-flash-image; gemini-3-pro-image = higher quality
```

Note on print resolution (§11.4): Gemini image models return ≈ 1024 px square by default → ≈ 120 DPI at full bleed (216 mm). Fine for proofs; for press-quality output select a higher-resolution model via `KB_IMAGE_MODEL`.

Cost control during development: `KB_LLM_MODEL=claude-haiku-4-5` (cheaper model) or `KB_LLM_PROVIDER=mock` + `KB_IMAGE_PROVIDER=mock` (fully offline, zero cost — exactly what the test suite and phase gates use).

## Fonts

Book content embeds fonts exclusively from `Global/fonts/` (deterministic output): Noto Sans + Noto Sans Thai, regular/bold — already downloaded from the official notofonts releases. See [Global/fonts/README.md](Global/fonts/README.md).

## Development

```bash
uv sync
uv run ruff check .     # lint
uv run ruff format .    # format
uv run mypy             # strict typing on src/
uv run pytest           # offline tests, no network
```

## Deliberate deviations from the spec

- **Package layout**: `src/kb/` (standard src-layout, importable package `kb`) instead of loose modules directly under `src/` — allowed by spec §5 ("internal module layout may be adjusted"), needed for clean packaging and the `kb` console script.
- **`docker/nginx.conf`** omitted: the web preview is a local single-user editor aid (`kb serve`, uvicorn on 127.0.0.1); fronting it with nginx adds no value at this scope.
- **questionary** not used: `--interactive` uses typer's built-in confirmation prompts, which cover the spec requirement without an extra dependency.
- **`word-break: keep-all`** (spec §11.3, pre-v5.1 wording): WeasyPrint ignores this property; Thai line segmentation is performed natively by Pango + libthai via `lang="th"` — verified by Gate 3. Spec updated accordingly.
- **Mock content is themed** (Swiss-Thai myths) and varies deterministically per prompt, so demo books have distinct pages/pictures while remaining fully reproducible.
- **Google images via Gemini API instead of Vertex AI Imagen**: classic Imagen `:predict` models are closed to new users (verified live, 2026-07). The `imagen` provider therefore calls Gemini image models (`generateContent`), which additionally accept reference images as input — a strict improvement for character consistency (HC-2.2/2.3). Auth is a simple `GOOGLE_API_KEY` instead of a service account.
