# Kinderbuch Agent – Implementation Spec (v4.0 Final)

**Goal**  
Build a lean, production-grade CLI application (`kb`) that creates bilingual (EN + TH) illustrated children’s books from idea to print-ready PDF.

**Layout**  
Real book geometry: left page = text only, right page = full-bleed image.  
**Languages**  
Internal model always uses ISO-639-1 codes (`en`, `th`). Display names only in templates/UI.

**Target audience of this document**  
Top-tier coding LLMs (Claude Opus, Mythos, o-series, Cursor Composer, etc.)

---

## Core Philosophy for the Implementing Agent

- Prefer simplicity, clarity, and elegance over cleverness.
- Follow modern, idiomatic Python.
- If you know a clearly better library or pattern that still satisfies every Hard Constraint → use it and briefly document why.
- Over-engineering is forbidden. Under-engineering the critical paths (consistency, Thai PDF, structured outputs, idempotency) is also forbidden.
- Write code that an experienced senior Python engineer would be happy to maintain.

---

# 1. Hard Constraints (Non-Negotiable)

These must never be violated. Violating any of them makes the solution unusable.

### 1.1 Data Model & LLM Outputs
- **Structured Outputs are mandatory** for Steps 01–04.  
  Use Anthropic’s native tool_use / structured outputs (or a very thin wrapper such as `instructor`).  
  **Never** use Markdown header parsing (`## English` / `## ไทย`) as the source of truth.
- Page text must be stored as:
  ```python
  text: dict[str, str]   # e.g. {"en": "...", "th": "..."}
  ```
- Human-readable Markdown files (for the editor) are **generated from** the structured data, never the other way around.

### 1.2 Visual Consistency (Highest Priority Quality Attribute)
- Every character has **exactly one Primary Reference Image**.
- When generating a page image, send **at most one primary reference image per character present** in that scene (hard upper limit ~3–4 reference images total).
- The image prompt must always include explicit spatial instructions  
  (“Character A matching reference image 1 stands on the left side of the image…”).
- Actively prevent reference bleed / identity mixing between characters.

### 1.3 PDF & Thai Typesetting
- Real physical book pages (separate pages for text and image).
- Correct 3 mm bleed + proper inner gutters.
- **Dockerfile must be based on `python:3.12-slim` (Debian).** Alpine is forbidden.
- Thai text must break correctly (`libthai` + `word-break: keep-all` + Noto Sans Thai).
- All fonts must be embedded from `Global/fonts/` (fully deterministic).

### 1.4 CLI & State Management
- `kb run` must be **idempotent by default**: already completed pages are skipped.
- Required flags: `--force`, `--recreate-images`, `--from-page`, `--pages`.
- All state lives in files (`book.yaml` + `pages/*.yaml`). No database.

### 1.5 Architecture Boundaries
- No LangChain, CrewAI, AutoGen, or any heavy agent framework.
- LLM and Image clients must be swappable (Abstract Base Class + concrete providers).
- All authentication (API keys, service accounts) lives only inside the concrete provider classes.

---

# 2. Recommended Stack (Opinionated but not dogmatic)

| Area                  | Recommended                              | Notes |
|-----------------------|------------------------------------------|-------|
| CLI                   | Typer + Rich + questionary              | Excellent DX. Click is acceptable. |
| Models / Validation   | Pydantic v2                              | Strongly preferred. |
| Structured Outputs    | Anthropic native or instructor           | Choose the cleaner/more stable option. |
| Parallel image gen    | asyncio + native async client            | Required for Step 04 performance. |
| PDF generation        | WeasyPrint + Jinja2 + CSS Paged Media    | Excellent for print. reportlab only if clearly superior. |
| Fonts                 | Noto Sans + Noto Sans Thai in `Global/fonts/` | Mandatory for determinism. |
| Retries / Backoff     | tenacity                                 | Strongly recommended. |
| Web preview           | FastAPI (minimal)                        | Editor-only. |
| Package manager       | uv (preferred) or poetry                 | — |
| Orchestration         | docker compose with volume mounts        | — |

You may choose better tools as long as every Hard Constraint remains satisfied and the codebase stays lean.

---

# 3. Project Structure (Guideline)

```
kinderbuch-agent/
├── Global/
│   ├── universes/                 # swiss-thai-myths, lord-of-the-rings, etc.
│   ├── system_prompts/
│   ├── fonts/                     # Noto Sans + Noto Sans Thai (required)
│   └── layouts/
├── Books/                         # one folder per book (volume-mounted)
├── src/
│   ├── cli.py
│   ├── core/                      # models, managers, steps/
│   ├── llm/
│   ├── image/                     # ImageProvider ABC + providers
│   ├── consistency/               # prompt_builder + reference_manager
│   ├── pdf/
│   └── web/
├── docker/
│   ├── Dockerfile                 # python:3.12-slim-bookworm only
│   ├── docker-compose.yml
│   └── nginx.conf
├── pyproject.toml
├── .env.example
└── README.md
```

You may adjust internal module layout if it becomes cleaner. Keep the top-level structure (Global/, Books/, docker/).

---

# 4. Minimal Domain Model

```python
class Page(BaseModel):
    number: int
    text: dict[str, str]                          # {"en": "...", "th": "..."}
    image_prompt: str | None = None
    image_path: Path | None = None
    characters_present: list[str] = []
    status: Literal["todo", "text_done", "image_done", "approved"] = "todo"

class Character(BaseModel):
    name: str
    role: str
    description: str
    primary_reference: Path | None = None
    visual_keywords: list[str] = []

class Book(BaseModel):
    slug: str
    title: str
    universe_slug: str
    languages: list[str]                          # ISO codes – single source of truth
    age_group: str = "4-6"
    characters: list[Character] = []
    pages: list[Page] = []
    # plus idea, outline, human-readable views, etc.
```

`Book.languages` inherits from the Universe at creation time and then becomes independent.

---

# 5. Pipeline (Outcome-Oriented)

| Step | Name                | Key Requirement                                      |
|------|---------------------|------------------------------------------------------|
| 01   | Outline             | Structured output                                    |
| 02   | Story               | Structured output + human-readable Markdown view     |
| 03   | Character Bible     | Bible + **exactly one primary reference sheet** per character |
| 04   | Pages               | Structured text + **parallel** image generation      |
| 05   | PDF                 | Real left/right pages, Thai support, 3 mm bleed, gutters |

Step 04 special rule: once texts and character sheets are ready, page image generation is embarrassingly parallel → use `asyncio.gather` (or equivalent).

---

# 6. Desired CLI Surface

```bash
kb --help
kb universe list | new | show
kb book new <slug> --universe <name> [--langs en,th] [--age 4-6]
kb book list | status | show <slug>

kb run <slug> [--force] [--recreate-images] [--from-page N] [--pages 3,5,7-9] [--interactive]
kb edit <slug> --page N --text-en "..." --text-th "..."
kb edit <slug> --page N --image "make the child happier..."
kb edit <slug> --bible "..."
kb edit <slug> --approve-page N

kb pdf <slug>
kb serve
kb open <slug>
```

`kb run` must be idempotent and resumable out of the box.

---

# 7. Docker & Developer Experience

- `docker compose up -d` brings everything up.
- Developer works with:
  ```bash
  docker compose exec app kb ...
  ```
- `./Books` and `./Global` are volume mounts → all Markdown files and images appear **immediately** on the host.
- Optional lightweight web preview on localhost (editor use only).

---

# 8. Definition of Done (Acceptance Criteria)

A phase is complete only when all of the following are true:

- `kb book new demo --universe swiss-thai-myths --langs en,th` works cleanly
- `kb run demo` is fully idempotent and can be interrupted and resumed safely
- Every character has exactly **one** primary reference image
- Multi-character pages never send more than one reference image per character
- `kb pdf demo` produces a print-ready multi-page PDF with:
  - Separate text and image pages
  - Correct Thai line breaking
  - Embedded fonts from `Global/fonts/`
  - 3 mm bleed + sensible gutters
- Docker image builds and runs without font/Pango issues
- Codebase is lean, well-typed, and easy to extend
- README clearly explains “First book in under 5 minutes”

---

# 9. Implementation Phases

### Phase 1 – Foundation (must be rock solid)
Project scaffold, domain models, Book/Universe managers, complete CLI surface (commands may still be stubs), Mock ImageProvider, Anthropic structured-output client, Dockerfile (`python:3.12-slim` + Thai dependencies + fonts), tenacity, working `kb --help`, basic README.

**After Phase 1: STOP.**  
Print `tree -L 3`, `kb --help`, and a short status report. Wait for human review.

### Phase 2 – Pipeline Core
Steps 01–04 with structured outputs, reference manager (multi-character logic), prompt builder (consistency + spatial instructions), parallel image generation, full idempotency + flags, interactive mode.

### Phase 3 – Output
Proper left/right page HTML/CSS, WeasyPrint with bleed/gutter/Thai, `kb pdf`, simple web preview, end-to-end example book.

### Phase 4 – Hardening
Real Google Imagen provider, tests for critical paths (reference selection, language inheritance, idempotency), final README polish, logging.

---

# 10. What You Should Excel At

- Write clean, idiomatic, modern Python.
- Make the critical sections (reference selection, structured output schemas, PDF CSS, idempotency logic) especially robust and readable.
- Prefer composition over deep inheritance.
- Add good type hints and concise docstrings.
- If you find a more elegant solution for parallel image generation, prompt construction, or PDF layout that still respects the constraints → use it.

---

# 11. Explicitly Forbidden

- Any agent framework (LangChain, CrewAI, etc.)
- Alpine Linux
- Markdown header parsing as source of truth
- Unlimited or high numbers of reference images
- Single wide landscape page containing both text and image
- Premature abstractions “for the future”
- Secrets in code

---

## Final Instructions to the Coding Agent

1. Read this entire document carefully.
2. Internalize the Hard Constraints.
3. Implement **Phase 1** to a high professional standard.
4. After Phase 1, stop and present:
   - `tree -L 3`
   - Output of `kb --help`
   - Short summary of what was built and any deliberate deviations
5. Wait for human feedback before starting Phase 2.

Produce code that makes a senior engineer say:  
**“This is clean, solid, and well thought out.”**

*Grok – 2026-07-13*  
*v4.0 Final – optimized for maximum quality from top coding LLMs*
