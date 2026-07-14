# Kinderbuch Agent

`kb` turns an idea into a bilingual (EN/TH) illustrated children's book as a print-ready PDF: outline → story → character bible → pages → PDF, via an idempotent, resumable pipeline.

The authoritative specification is [implementation-spec.md](implementation-spec.md). The complete command and flag reference is in [docs/MANUAL.md](docs/MANUAL.md); architecture and workflow diagrams are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Status

| Phase | State | Gate |
|---|---|---|
| 1 — Foundation | ✅ complete | quality gates + Docker image validated (kb, WeasyPrint, libthai, Pango) |
| 2 — Pipeline Core | ✅ complete | Gate 2: offline `kb run` e2e, idempotency, resume ([tests/test_e2e_run.py](tests/test_e2e_run.py)) |
| 3 — Output (PDF + preview) | ✅ complete | Gate 3: offline `kb run && kb pdf` → bilingual EN/TH PDF, zero LLM cost ([tests/test_e2e_pdf.py](tests/test_e2e_pdf.py)) |
| 4 — Hardening (Google images, polish) | ✅ complete | Gate 4: full §13 suite; real provider config-selectable, never exercised by tests |

All pipeline steps (outline → story → character bible → pages) run with structured LLM outputs, visual-consistency reference management, and parallel image generation. `kb pdf` produces a print-ready PDF: 216 × 216 mm pages (3 mm bleed), verso text / recto full-bleed image spreads, embedded Noto fonts, libthai-backed Thai line breaking, and age-aware typography (larger type for pre-readers, book-sized type for young adults). Example books in `Books/`:

- `demo` — offline (mock) example, zero cost
- `ninos-two-mountains` — real-generated picture book (age 4-6, 5 spreads)
- `the-weight-of-water` — real-generated young-adult book (age 12-14, 10 spreads, own universe/style) about climate change between a Swiss glacier village and the Chao Phraya delta

## Quickstart

### Local (uv)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv is missing
uv sync
uv run kb --help
alias kb='uv run kb'          # the rest of this README assumes this alias (or use Docker)
```

For real generation, create your .env first:

```bash
cp .env.example .env          # then fill in ANTHROPIC_API_KEY (+ GOOGLE_API_KEY for images)
```

### Docker

```bash
cp .env.example .env          # fill in ANTHROPIC_API_KEY for real LLM use
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml exec app kb --help
```

`./Books` and `./Global` are bind-mounted — generated files appear on the host immediately. The container runs as your host UID/GID (default `1000:1000`, override with `UID=$(id -u) GID=$(id -g) docker compose … up`), so generated books stay editable on the host. Real images need `KB_IMAGE_PROVIDER=imagen` + `GOOGLE_API_KEY` in `.env` — otherwise the PDF gets placeholder pictures. For the web preview inside Docker, bind all interfaces so the host can reach the published port:

```bash
docker compose -f docker/docker-compose.yml exec app kb serve --host 0.0.0.0
# then open http://127.0.0.1:8000 in your host browser
```

## First book in under 5 minutes

```bash
kb universe list                                  # ships with swiss-thai-myths
kb book new nino --universe swiss-thai-myths --langs en,th --age 4-6 \
  --idea "Nino, a curious four-year-old, visits his Thai grandmother for the first time"
kb run nino                # full pipeline; use KB_LLM_PROVIDER=mock KB_IMAGE_PROVIDER=mock for a free dry run
kb pdf nino                # → Books/nino/build/nino.pdf (print-ready)
kb serve                   # web preview at http://127.0.0.1:8000
kb open nino               # open the book in the preview
kb book status nino
```

Small changes via CLI — view, optimize, regenerate:

```bash
kb book show demo --page 2                              # read a page: all languages + image prompt
kb edit demo --page 2 --text "make it shorter, punchier" # LLM rewrite of ALL languages at once
kb edit demo --page 2 --text-en "..." --text-th "..."    # manual replacement (§6.2)
kb edit demo --page 2 --image "make the child happier"   # regenerate just that image
kb edit demo --bible "give the naga a red scarf"
kb edit demo --approve-page 2
kb run demo --recreate-images                            # ALL images fresh: references first, then pages
kb run demo --recreate-images --pages 3,5-7              # selective regeneration (page images only)
kb pdf demo                                              # re-render after any edit
```

Older readers, longer books, own style — create a universe with its own illustration
style and use `--age`/`--spreads`; prose level and typography adapt automatically:

```bash
kb universe new alpine-monsoon --langs en,th --style "cinematic graphic-novel, ink and watercolor"
kb book new the-weight-of-water --universe alpine-monsoon --age 12-14 --spreads 10 --idea "..."
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

Note on content safety: if Google's filter refuses a scene (dark/violent motifs), the run summary names the page and the fix — soften it with `kb edit <slug> --page N --image "symbolic and dreamlike, no gore"`; retrying alone never helps.

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
