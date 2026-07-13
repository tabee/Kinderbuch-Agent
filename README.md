# Kinderbuch Agent

`kb` turns an idea into a bilingual (EN/TH) illustrated children's book as a print-ready PDF: outline → story → character bible → pages → PDF, via an idempotent, resumable pipeline.

The authoritative specification is [implementation-spec.md](implementation-spec.md).

## Status

**Phase 1 (Foundation) — complete.** Domain models, atomic YAML persistence, full CLI surface, mock image provider, Anthropic structured-output client, Docker setup, tests.

Pending (spec §15): Phase 2 pipeline steps, Phase 3 PDF/web preview, Phase 4 Google Imagen provider + hardening.

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
kb book status demo
kb run demo                                                 # pipeline — Phase 2
kb pdf demo                                                 # print-ready PDF — Phase 3
```

## Configuration

All configuration is via environment variables (`.env` supported locally); see [.env.example](.env.example) for the full annotated list. Provider credentials are only ever read inside the concrete provider classes.

## Fonts

Book content embeds fonts exclusively from `Global/fonts/` (deterministic output). See [Global/fonts/README.md](Global/fonts/README.md) for the required files.

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
- **`docker/nginx.conf`** is deferred to Phase 3, when the web preview it would front actually exists.
- **questionary / FastAPI** are not yet dependencies; they are added in the phase that uses them (interactive mode in Phase 2, web preview in Phase 3) to keep the dependency tree lean.
- **WeasyPrint/Jinja2** are already declared as dependencies although rendering lands in Phase 3, so the Docker image build validates the Pango/libthai runtime from day one.
