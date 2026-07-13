# Kinderbuch Agent — Implementation Specification

| | |
|---|---|
| **Version** | 5.1 |
| **Status** | Approved for implementation |
| **Date** | 2026-07-13 |
| **Supersedes** | v5.0 (adds per-phase verification gates and the mock LLM provider) |
| **Audience** | Implementing engineer or autonomous coding agent |

---

## 1. Overview

### 1.1 Product Summary

`kb` is a lean, production-grade CLI application that takes an illustrated children's book from initial idea to print-ready PDF. Books are bilingual (English and Thai) and use real book geometry: each spread consists of a left (verso) page containing only text and a right (recto) page containing a full-bleed illustration.

The internal data model always uses ISO 639-1 language codes (`en`, `th`); human-readable language names appear only in templates and UI.

### 1.2 Goals

- **G-1** Generate a complete book (outline → story → character bible → pages → PDF) from a single idea via a resumable, idempotent pipeline.
- **G-2** Guarantee visual character consistency across all illustrations.
- **G-3** Produce typographically correct bilingual output, including proper Thai line breaking.
- **G-4** Keep the codebase small and clear enough for a single senior engineer to maintain.

### 1.3 Non-Goals

The following are explicitly out of scope:

- Multi-user operation, authentication, or hosted/SaaS deployment. The web preview is a local, single-user editing aid.
- Databases of any kind. All state lives in files (HC-4.3).
- E-book formats (EPUB, MOBI).
- CMYK conversion and ICC color management. The workflow is RGB, targeting digital print (§11.4).
- Proving languages beyond `en`/`th`. The model is language-generic, but only the bilingual EN/TH path must be validated.

### 1.4 Terminology

| Term | Definition |
|------|------------|
| Universe | A reusable setting (style guide, tone, recurring characters) from which books are created. |
| Book | One story project, fully owned by its state files under `Books/<slug>/`. |
| Spread | A pair of facing pages: verso text page + recto image page. |
| Character Bible | Structured character descriptions produced in Step 03. |
| Primary Reference Image | The single canonical image per character, used as the identity reference for all page illustrations. |
| Reference bleed | Unwanted mixing of one character's visual identity into another during image generation. |
| Structured output | LLM output constrained to a schema (native tool use) and validated into Pydantic models. |

---

## 2. Guiding Principles

- Prefer simplicity, clarity, and elegance over cleverness. Follow modern, idiomatic Python.
- Prefer composition over deep inheritance. Use full type hints and concise docstrings on public APIs.
- If a clearly better library or pattern satisfies every Hard Constraint, use it and briefly document the rationale.
- Over-engineering is forbidden. Under-engineering the critical paths (visual consistency, Thai PDF output, structured outputs, idempotency) is equally forbidden.
- Write code that an experienced senior Python engineer would be happy to maintain.

---

## 3. Hard Constraints (Non-Negotiable)

Every constraint carries a stable ID (`HC-x.y`) so that code review, tests, and acceptance criteria can reference it. Violating any HC makes the deliverable unacceptable.

### 3.1 Data Model & LLM Outputs

- **HC-1.1** Steps 01–04 MUST use structured outputs (Anthropic native tool use / structured outputs, or a very thin wrapper such as `instructor`). Free-text parsing — in particular Markdown header parsing (`## English` / `## ไทย`) — MUST NOT be a source of truth.
- **HC-1.2** Page text MUST be stored keyed by ISO 639-1 code:

  ```python
  text: dict[str, str]   # e.g. {"en": "...", "th": "..."}
  ```

- **HC-1.3** Human-readable Markdown files are generated views derived from structured state. They are never parsed back into the model.

### 3.2 Visual Consistency (Highest-Priority Quality Attribute)

- **HC-2.1** Every character has exactly one Primary Reference Image.
- **HC-2.2** A page-image request includes at most one reference image per character present in the scene, and never more than 4 reference images in total. If a scene contains more than 4 characters, references are used for the first 4 entries of `characters_present` (which Step 04 orders by narrative salience).
- **HC-2.3** Every image prompt contains explicit spatial anchoring that binds each reference image to a named character and a position ("Anna, matching reference image 1, stands on the left side of the image …").
- **HC-2.4** The prompt builder actively mitigates reference bleed: distinct visual keywords per character and unambiguous reference-to-character binding in every prompt.

### 3.3 PDF & Thai Typesetting

- **HC-3.1** Text and image are separate physical pages (§11.2). A single wide landscape page combining both is forbidden.
- **HC-3.2** 3 mm bleed on all sides and correct inner gutters, per the geometry in §11.1.
- **HC-3.3** The Dockerfile MUST be based on `python:3.12-slim` (Debian bookworm). Alpine is forbidden.
- **HC-3.4** Thai text MUST break correctly: `libthai` available to Pango (which performs Thai line segmentation natively), `lang="th"` on Thai content, rendered in Noto Sans Thai.
- **HC-3.5** All fonts are embedded from `Global/fonts/`. No system-font fallback for book content (full determinism).

### 3.4 CLI & State Management

- **HC-4.1** `kb run` is idempotent by default: completed artifacts are skipped, and an interrupted run resumes safely with no manual cleanup.
- **HC-4.2** The flags `--force`, `--recreate-images`, `--from-page`, and `--pages` MUST exist with the exact semantics defined in §8.2.
- **HC-4.3** All state lives in files (`book.yaml` + `pages/*.yaml`). No database.
- **HC-4.4** All state writes are atomic (write to a temporary file in the same directory, then `os.replace`).

### 3.5 Architecture Boundaries

- **HC-5.1** No LangChain, CrewAI, AutoGen, or any other heavy agent framework.
- **HC-5.2** LLM and image clients are swappable: one Abstract Base Class each, plus concrete providers selected via configuration (§9).
- **HC-5.3** Credentials (API keys, service accounts) live only inside concrete provider classes and are sourced exclusively from environment variables. No secrets in code, state files, or logs.

---

## 4. Technology Stack (Opinionated, Not Dogmatic)

| Area                  | Recommended                                   | Notes |
|-----------------------|-----------------------------------------------|-------|
| CLI                   | Typer + Rich + questionary                    | Excellent DX. Click is acceptable. |
| Models / validation   | Pydantic v2                                   | Strongly preferred. |
| Structured outputs    | Anthropic native or `instructor`              | Choose the cleaner, more stable option. |
| Parallel image gen    | `asyncio` + native async client               | Required for Step 04 performance (§7.3). |
| PDF generation        | WeasyPrint + Jinja2 + CSS Paged Media         | Excellent for print. `reportlab` only if clearly superior. |
| Fonts                 | Noto Sans + Noto Sans Thai in `Global/fonts/` | Mandatory for determinism (HC-3.5). |
| Retries / backoff     | tenacity                                      | Resilience policy in §10. |
| Web preview           | FastAPI (minimal)                             | Local editor aid only. |
| Package manager       | uv (preferred) or poetry                      | — |
| Orchestration         | docker compose with volume mounts             | — |

Better tools may be substituted as long as every Hard Constraint remains satisfied and the codebase stays lean. Document any substitution and its rationale in the README.

---

## 5. Project Structure (Guideline)

```
kinderbuch-agent/
├── Global/
│   ├── universes/                 # swiss-thai-myths, lord-of-the-rings, etc.
│   ├── system_prompts/
│   ├── fonts/                     # Noto Sans + Noto Sans Thai (required)
│   └── layouts/                   # trim size, margins, gutter definitions (§11.1)
├── Books/                         # one folder per book (volume-mounted, §6.3)
├── src/
│   ├── cli.py
│   ├── core/                      # models, managers, steps/
│   ├── llm/                       # LLMProvider ABC + providers
│   ├── image/                     # ImageProvider ABC + providers
│   ├── consistency/               # prompt_builder + reference_manager
│   ├── pdf/
│   └── web/
├── docker/
│   ├── Dockerfile                 # python:3.12-slim (bookworm) only
│   ├── docker-compose.yml
│   └── nginx.conf
├── tests/
├── pyproject.toml
├── .env.example                   # every variable from §9, with comments
└── README.md
```

The internal module layout may be adjusted if it becomes cleaner. The top-level structure (`Global/`, `Books/`, `docker/`) is fixed.

---

## 6. Domain Model & Persistence

### 6.1 Core Models

```python
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

PageStatus = Literal["todo", "text_done", "image_done", "approved"]


class Page(BaseModel):
    number: int                                   # 1-based, contiguous
    text: dict[str, str] = Field(default_factory=dict)  # keyed by ISO 639-1 code
    image_prompt: str | None = None
    image_path: Path | None = None                # relative to the book directory
    characters_present: list[str] = Field(default_factory=list)  # Character.slug, salience order
    status: PageStatus = "todo"


class Character(BaseModel):
    slug: str                                     # stable kebab-case identifier
    name: str
    role: str
    description: str
    primary_reference: Path | None = None         # relative to the book directory
    visual_keywords: list[str] = Field(default_factory=list)


class Book(BaseModel):
    schema_version: int = 1
    slug: str
    title: str
    universe_slug: str
    languages: list[str]                          # ISO 639-1 codes — single source of truth
    age_group: str = "4-6"
    idea: str = ""
    characters: list[Character] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    # plus outline and other step artifacts as structured fields
```

Rules:

- `Book.languages` is copied from the Universe at creation time and is independent afterwards.
- All stored paths are relative to the book directory, so a book folder is fully portable.
- `schema_version` is written to every `book.yaml`; loading a version newer than the code supports fails with a clear error.

### 6.2 Page Status Lifecycle

```
todo ──▶ text_done ──▶ image_done ──▶ approved
```

- `kb run` advances pages left to right and, by default, never repeats completed work (HC-4.1). Approved pages are never modified without `--force`.
- Text edit (`kb edit --text-*`): updates text and revokes approval; status becomes `text_done` if no image exists, otherwise `image_done`.
- Image edit (`kb edit --image "..."`): regenerates the image with the edit instruction appended to the original prompt; revokes approval; status becomes `image_done`.
- `kb edit --approve-page N`: transitions `image_done → approved` only; any other source state is an error.

### 6.3 On-Disk Layout per Book

```
Books/<slug>/
├── book.yaml                      # Book model minus pages
├── pages/                         # 001.yaml, 002.yaml, ... (one Page per file)
├── references/                    # <character-slug>.png — primary reference images
├── images/                        # page-001.png, ... — page illustrations
├── views/                         # generated Markdown (story.md, bible.md); never parsed
└── build/                         # HTML intermediates + final PDF
```

- Every state mutation is persisted immediately and atomically (HC-4.4), so a killed process never leaves corrupt state.
- `views/` and `build/` are disposable derived artifacts, safe to delete at any time.

---

## 7. Pipeline Specification

### 7.1 Steps

| Step | Name            | Input                      | Output (structured, HC-1.1) |
|------|-----------------|----------------------------|------------------------------|
| 01   | Outline         | Idea + universe context    | Structured outline |
| 02   | Story           | Outline                    | Structured story + generated Markdown view |
| 03   | Character Bible | Story                      | Structured bible + exactly one primary reference image per character (HC-2.1) |
| 04   | Pages           | Story + bible + references | Structured per-page text and image prompts + page images (parallel, §7.3) |
| 05   | PDF             | Pages + layout + fonts     | Print-ready PDF (§11) |

### 7.2 Step Details

- **Step 03 — reference images.** For each character, generate one full-body reference: neutral pose, plain light background, no scene props, rendered in the universe's style. Stored as `references/<character-slug>.png`. This image is the sole identity source for that character on every page (HC-2.1/2.2).
- **Step 04 — page text.** One structured object per page: `text` for every configured language, `image_prompt`, and `characters_present` ordered by narrative salience (consumed by HC-2.2).
- **Structured-output validation.** If an LLM response fails Pydantic validation, re-prompt with the validation errors appended, at most 2 additional attempts, then fail the step with a clear error. Never silently accept partially valid data.

### 7.3 Parallel Image Generation (Step 04)

Once texts and reference images exist, page image generation is embarrassingly parallel:

- Use `asyncio.gather` behind an `asyncio.Semaphore` with bounded concurrency (`KB_MAX_CONCURRENCY`, default 4) to respect provider rate limits.
- Per-page failure isolation: one failed page never aborts its siblings.
- Each page's state is persisted immediately upon success, so an interrupted run resumes exactly where it stopped.
- At the end of the run, print a summary of failed pages; exit non-zero if any page failed (§8.3).

---

## 8. CLI Specification

### 8.1 Command Surface

```bash
kb --help
kb universe list | new | show
kb book new <slug> --universe <name> [--langs en,th] [--age 4-6] [--idea "..."] [--spreads N]
kb book list | status | show <slug>

kb run <slug> [--force] [--recreate-images] [--from-page N] [--pages 3,5,7-9] [--interactive]
kb edit <slug> --page N --text "make it shorter..."      # LLM rewrite, all languages
kb edit <slug> --page N --text-en "..." --text-th "..."  # manual replacement
kb edit <slug> --page N --image "make the child happier..."
kb edit <slug> --bible "..."
kb edit <slug> --approve-page N
kb book show <slug> [--page N]                           # full page text + image prompt

kb pdf <slug>
kb serve
kb open <slug>
```

### 8.2 `kb run` Flag Semantics (HC-4.2)

| Flag | Semantics |
|------|-----------|
| *(default)* | Idempotent: skip every artifact that already exists; never touch `approved` pages. |
| `--force` | Regenerate all selected artifacts regardless of status, including `approved` pages. |
| `--recreate-images` | Regenerate images only; texts are kept. Approval is revoked on affected pages. |
| `--from-page N` | Restrict page-level work to pages with `number >= N`. |
| `--pages SPEC` | Restrict to a page set. Grammar: comma-separated integers and inclusive ranges, e.g. `3,5,7-9`. Invalid specs are a usage error. |
| `--interactive` | Pause for confirmation between pipeline steps. |

Page-selection flags combine by intersection. Steps 01–03 run only if their artifacts are missing (or with `--force`).

### 8.3 Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | Runtime failure, including partial failure (e.g. some page images failed). |
| 2 | Usage error (unknown book, invalid `--pages` spec, invalid flag combination). |

---

## 9. Configuration

All configuration is via environment variables, read once at startup (`.env` supported for local development). `.env.example` MUST list every variable with a comment.

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `ANTHROPIC_API_KEY` | for real LLM use | — | Anthropic authentication. |
| `KB_LLM_PROVIDER` | no | `anthropic` | LLM provider selection: `anthropic` or `mock` (offline, deterministic, zero cost). |
| `KB_LLM_MODEL` | no | provider default | Anthropic model ID; set a cheaper model (e.g. a Haiku-class model) for low-cost development. |
| `KB_IMAGE_PROVIDER` | no | `mock` | Image provider selection: `mock` or `imagen`. |
| `KB_IMAGE_MODEL` | no | provider default | Gemini image model ID (default `gemini-3.1-flash-image`; `gemini-3-pro-image` for higher quality). |
| `GOOGLE_API_KEY` | for `imagen` | — | Google AI Studio key (Gemini API). The `imagen` provider targets current Gemini image models; classic Imagen `:predict` models are closed to new users (verified 2026-07). |
| `GOOGLE_APPLICATION_CREDENTIALS` | no | — | Service-account JSON for the optional Vertex AI route. |
| `KB_MAX_CONCURRENCY` | no | `4` | Maximum parallel image-generation requests. |
| `KB_LOG_LEVEL` | no | `INFO` | Logging verbosity. |

Providers validate their own configuration at instantiation and fail fast with an actionable message (HC-5.3).

Both provider families ship an offline mock implementation. The mocks are deterministic, require no credentials, and make no network calls — they power the test suite and the phase verification gates (§15).

---

## 10. Resilience, Logging & Error Handling

- **Retries.** All provider calls are wrapped with tenacity: exponential backoff with jitter, at most 5 attempts, retrying only transient failures (HTTP 429, 5xx, network errors). Authentication and validation errors (4xx) are never retried.
- **Logging.** Standard `logging` with human-readable output via Rich; level from `KB_LOG_LEVEL`. Retries log at `WARNING`. Never log secrets, API keys, or raw base64 image payloads.
- **Failure reporting.** Every user-facing error states what failed, for which book/page, and the most likely remediation.

---

## 11. PDF & Print Specification

### 11.1 Geometry

- Page geometry is defined per layout in `Global/layouts/`. Default layout: **210 × 210 mm trim**, 3 mm bleed on all sides (final page media box 216 × 216 mm) — HC-3.2.
- Text pages: inner (gutter) margin ≥ 20 mm; all other margins ≥ 12 mm. No text within 5 mm of the trim line.
- Image pages: the illustration extends to the full bleed box.

### 11.2 Page Sequence

- Each spread: verso (left) page = text only, recto (right) page = full-bleed image (HC-3.1).
- A minimal title page is allowed as front matter; keep it simple.
- PDF metadata (title, primary language) is set on the output document.

### 11.3 Typography

- Fonts exclusively from `Global/fonts/` via `@font-face`, fully embedded in the PDF (HC-3.5).
- Thai content is wrapped in elements with `lang="th"`, uses Noto Sans Thai, and relies on `libthai`-backed Pango line breaking (HC-3.4). WeasyPrint ignores `word-break`; libthai performs the segmentation.

### 11.4 Color & Resolution

- RGB workflow; CMYK conversion is out of scope (§1.3).
- Request page images at the highest square resolution the provider supports (hard floor 1024 × 1024). No artificial upscaling. Document the resulting effective DPI in the README; 300 DPI at full bleed (≈ 2551 px) is the ideal target.

---

## 12. Docker & Developer Experience

- `docker compose up -d` brings everything up; the developer works via `docker compose exec app kb ...`.
- `./Books` and `./Global` are volume mounts: all Markdown files, images, and PDFs appear immediately on the host.
- The image is based on `python:3.12-slim` (HC-3.3) and installs the WeasyPrint/Thai runtime dependencies (Pango, cairo, `libthai`, GDK-PixBuf). Book fonts come from the mounted `Global/fonts/`, not from system packages.
- Optional lightweight web preview on localhost (editor use only).

---

## 13. Quality & Testing

- Lint/format: `ruff check` and `ruff format` pass cleanly.
- Types: `mypy` (or pyright) passes on `src/` with a strict-leaning configuration.
- Tests (pytest) MUST cover the critical paths and MUST NOT require network access (use the mock providers):
  - Reference selection for multi-character scenes (HC-2.2), including the > 4-character cap.
  - Language inheritance from Universe to Book.
  - Idempotency and status transitions (`run`, `--force`, `--recreate-images`, edit semantics from §6.2).
  - `--pages` spec parsing, including invalid inputs.
  - Atomic persistence round-trip (Book/Page → YAML → Book/Page).
- **Offline end-to-end gate.** With `KB_LLM_PROVIDER=mock` and `KB_IMAGE_PROVIDER=mock`, `kb run` followed by `kb pdf` MUST produce a bilingual multi-page PDF with placeholder images — no network access, zero API cost. Assertions are programmatic (page count, both languages present, fonts embedded; e.g. via `pypdf` as a dev dependency). This test is introduced incrementally by the phase gates (§15) and must remain green permanently once added.

---

## 14. Acceptance Criteria (Definition of Done)

The project is complete only when all of the following hold:

- `kb book new demo --universe swiss-thai-myths --langs en,th` works cleanly.
- `kb run demo` is fully idempotent and can be interrupted and resumed safely (HC-4.1).
- Every character has exactly one primary reference image (HC-2.1).
- Multi-character pages never exceed the reference limits (HC-2.2).
- `kb pdf demo` produces a print-ready multi-page PDF with separate text/image pages, correct Thai line breaking, fonts embedded from `Global/fonts/`, and 3 mm bleed plus correct gutters (§11).
- The Docker image builds and runs without font or Pango issues (HC-3.3/3.4).
- All quality gates in §13 pass.
- The README explains "First book in under 5 minutes".

---

## 15. Implementation Phases

Every phase ends with a **verification gate**: an automated, offline, zero-API-cost check that proves the phase works. A phase is not complete until its gate passes, and all earlier gates must remain green. Gates are implemented as pytest tests (using the mock providers) plus the §13 quality gates (ruff, mypy, pytest).

### Phase 1 — Foundation (must be rock solid)

Project scaffold, domain models (§6), Book/Universe managers with atomic persistence, complete CLI surface (commands may still be stubs), mock LLM and image providers, Anthropic structured-output client, Dockerfile (`python:3.12-slim` + Thai/Pango dependencies), tenacity wiring, working `kb --help`, basic README.

**Gate 1:** quality gates pass; `kb --help` exits 0; `kb book new demo --universe swiss-thai-myths --langs en,th` produces a valid `book.yaml` with inherited languages; exit-code semantics (§8.3) covered by tests; both mock providers produce deterministic output offline.

**Exit criterion — STOP after Phase 1.** Present `tree -L 3`, the output of `kb --help`, and a short status report. Wait for human review before continuing.

### Phase 2 — Pipeline Core

Steps 01–04 with structured outputs, reference manager (multi-character logic, HC-2.2), prompt builder (consistency + spatial anchoring, HC-2.3/2.4), parallel image generation (§7.3), full idempotency and flag semantics (§8.2), interactive mode.

**Gate 2 (offline pipeline run):** with both mock providers, `kb run demo` completes Steps 01–04 — every page has text in every configured language plus a placeholder image, every character has exactly one reference image (HC-2.1); an immediately repeated `kb run demo` is a no-op (HC-4.1); an interrupted run resumes cleanly.

### Phase 3 — Output

Left/right page HTML/CSS, WeasyPrint with bleed/gutter/Thai (§11), `kb pdf`, simple web preview, one end-to-end example book.

**Gate 3 (offline book production — the final product test):** with both mock providers, `kb run demo && kb pdf demo` produces a complete bilingual (EN/TH) children's book PDF with placeholder images at **zero LLM cost**: correct page count (text/image page per spread), Thai and English text present, fonts embedded from `Global/fonts/`, 216 × 216 mm page geometry. Asserted programmatically in the test suite.

### Phase 4 — Hardening

Real Google Imagen provider, full test coverage per §13, logging polish, final README.

**Gate 4:** the complete §13 suite passes, including all earlier gates; the `imagen` provider is selectable via configuration but never exercised by tests; §14 acceptance criteria hold end to end.

---

## 16. Explicitly Forbidden

- Any agent framework (LangChain, CrewAI, AutoGen, …) — HC-5.1.
- Alpine Linux — HC-3.3.
- Markdown parsing as a source of truth — HC-1.1/1.3.
- Unlimited or excessive reference images — HC-2.2.
- A single wide landscape page containing both text and image — HC-3.1.
- Premature abstractions "for the future".
- Secrets in code, state files, or logs — HC-5.3.
- Network access in tests.

---

## 17. Assumptions & Defaults

The following defaults were chosen by this specification. They may be changed without a spec revision, provided the change is documented in the README:

- Trim size 210 × 210 mm (§11.1).
- Image-generation concurrency limit of 4 (§9).
- Retry policy: 5 attempts, exponential backoff with jitter (§10).
- Structured-output validation: at most 2 corrective re-prompts (§7.2).

---

## 18. Final Instructions to the Implementer

1. Read this entire document and internalize the Hard Constraints (§3).
2. Implement **Phase 1** to a high professional standard.
3. After Phase 1, stop and present: `tree -L 3`, the output of `kb --help`, and a short summary of what was built plus any deliberate deviations (with rationale).
4. Wait for human feedback before starting Phase 2.

The quality bar: code that makes a senior engineer say, "This is clean, solid, and well thought out."
