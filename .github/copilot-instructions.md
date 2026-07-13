# Kinderbuch Agent — Project Guidelines

`kb` is a CLI application that turns an idea into a bilingual (EN/TH) illustrated children's book as a print-ready PDF. Greenfield project.

## Authoritative Specification

[implementation-spec.md](../implementation-spec.md) (v5.1) is the single source of truth. Read it before implementing anything. Requirements carry stable IDs (`HC-x.y` = Hard Constraint, `§n` = section) — reference them in code comments, commit messages, and test names where relevant.

## Hard Constraints (summary — full text in spec §3)

Never violate these; when in doubt, re-read the spec section:

- **HC-1.x** Structured LLM outputs only (native tool use / `instructor`); Markdown is a generated view, never parsed back. Page text is `dict[str, str]` keyed by ISO 639-1 codes.
- **HC-2.x** Exactly one primary reference image per character; ≤ 1 reference per character and ≤ 4 total per image request; every image prompt spatially binds each reference to a named character.
- **HC-3.x** Separate text/image pages; 3 mm bleed + gutters per §11; Docker base `python:3.12-slim` (never Alpine); Thai line breaking via libthai + Noto Sans Thai; fonts embedded only from `Global/fonts/`.
- **HC-4.x** `kb run` idempotent by default; flag semantics exactly per §8.2; all state in YAML files; atomic writes (temp file + `os.replace`).
- **HC-5.x** No agent frameworks (LangChain, CrewAI, AutoGen); LLM/image providers behind ABCs, selected via config; secrets only from env vars inside concrete providers.

## Phase Discipline

Work proceeds in phases (spec §15). **Stop after Phase 1** and present `tree -L 3`, `kb --help` output, and a status report. Do not start a later phase without explicit human approval. Every phase ends with its verification gate (spec §15): offline pytest tests using both mock providers, zero API cost; earlier gates must stay green.

## Architecture

- `src/core/` models + managers + pipeline steps, `src/llm/` + `src/image/` provider ABCs and implementations, `src/consistency/` prompt builder + reference manager, `src/pdf/`, `src/web/`. Top-level `Global/`, `Books/`, `docker/` layout is fixed (spec §5).
- All book state lives under `Books/<slug>/` with relative paths (spec §6.3). `views/` and `build/` are disposable derived artifacts.

## Build and Test

Package manager: `uv`. Once scaffolded:

```bash
uv sync                 # install
uv run ruff check .     # lint — must pass clean
uv run ruff format .    # format
uv run mypy src/        # types — must pass clean
uv run pytest           # tests — offline only, no network
```

## Conventions

- Modern idiomatic Python 3.12, Pydantic v2, full type hints, composition over inheritance.
- Languages are ISO 639-1 codes internally; display names only in templates/UI.
- No over-engineering: no premature abstractions, no features beyond the spec. Deviations from the recommended stack are allowed only if every HC still holds — document rationale in the README.
