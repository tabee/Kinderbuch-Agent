# kb — User Manual

Complete reference for every command, flag, and configuration variable. For a
guided introduction see the [README](../README.md); for design rationale see the
[implementation specification](../implementation-spec.md).

**Invocation.** Installed via `uv sync`, run as `uv run kb …` (or set
`alias kb='uv run kb'`). In Docker: `docker compose -f docker/docker-compose.yml exec app kb …`.
All commands operate relative to the current working directory, which must
contain the `Global/` and `Books/` folders.

---

## 1. Global options

| Option | Description |
|---|---|
| `--version` | Print the kb version and exit. |
| `--help` | Available on every command and subcommand. |

## 2. Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | Runtime failure — including partial failure (e.g. some page images failed) and aborted interactive runs. |
| `2` | Usage error — unknown book/universe, invalid `--pages` spec, invalid flag combination, missing required flag. |

---

## 3. `kb assistant` — guided creation and review

```bash
kb assistant [<slug>] [--temperature X]
```

Without a slug, the assistant starts with an existing or new universe and then
creates a book. With an existing book slug, it resumes from the persisted YAML
state. It guides the complete workflow:

```
universe → book idea → outline → story → character bible → every page → PDF
```

At each review the assistant shows the current artifact in a panel, a progress
header (`Schritt 3/7 · Outline`), and a numbered action menu that explains every
option. Select an action by its **number** (`1`), its **key letter** (`a`, `m`,
`l`, `q`, …) or a **word** (`freigeben`, `manuell`, `llm`, `pausieren`);
pressing Enter picks the highlighted default (approve). All creative stages
support approval, manual replacement, or a free-form instruction to the
configured LLM. Page reviews separately support manual or LLM-assisted text
revision and image revision. Approving a page moves it to `approved`; only
after every unfinished page has been reviewed does the assistant render the
PDF.

**LLM creativity is adjustable at any time.** Every action menu shows the
current value in its footer; type `temp` (or `temperatur`) at the `Auswahl`
prompt to change it mid-session — `0.0` = focused and reproducible, `1.0` =
most varied, empty input = back to the provider default. The change takes
effect on the next LLM request. Start with a specific value via
`kb assistant --temperature 0.8` or set a lasting default with
`KB_LLM_TEMPERATURE` (§10).

Choose `q` at any review to pause. All completed work is already stored
atomically; resume with the command printed by the assistant:

```bash
kb assistant my-book
```

Changing an outline removes its old story, bible, pages, page images, and stale
PDF; changing a story removes its old bible and page outputs. They are generated
again only after the revised upstream artifact is approved. This prevents mixed
versions. Provider and cost settings are the same as for `kb run`.

## 4. `kb universe` — reusable story settings

A *universe* defines the world, tone, languages, and illustration style that
books inherit at creation time.

### `kb universe list`

List all universes with slug, name, and languages.

### `kb universe new <slug> [options]`

```
kb universe new <slug> [--name TEXT] [--langs TEXT] [--description TEXT] [--style TEXT]
```

`<slug>` is **positional**: write it right after `new`, with no `--` prefix —
there is no `--slug` flag. Options may follow in any order.

| Flag | Default | Description |
|---|---|---|
| `<slug>` | — | Positional, not a flag. Kebab-case identifier (`[a-z0-9-]`), e.g. `swiss-thai-myths`. |
| `--name TEXT` | title-cased slug | Display name. |
| `--langs TEXT` | `en,th` | Comma-separated ISO 639-1 codes. |
| `--description TEXT` | empty | World description; feeds the outline step. |
| `--style TEXT` | empty | Illustration style guide applied to **every** image (references and pages). |

```bash
kb universe new duesterwald --name "Düsterwald" --langs de,en \
  --description "A dark, spooky forest where children get lost every time they go in" \
  --style "black and white manga, only red for eyes, fire, or blood"
```

### `kb universe show <slug>`

Print a universe's name, languages, description, and style guide.

---

## 5. `kb book` — book management

### `kb book new <slug> --universe <name> [options]`

```
kb book new <slug> --universe <name> [--langs TEXT] [--age TEXT] [--idea TEXT] [--spreads N]
```

`<slug>` is **positional**: write it right after `new`, with no `--` prefix —
there is no `--slug` flag. Options may follow in any order.

| Flag | Default | Description |
|---|---|---|
| `<slug>` | — | Positional, not a flag. Kebab-case identifier; also the folder name under `Books/`. |
| `--universe TEXT` | required | Universe the book belongs to. |
| `--langs TEXT` | universe's languages | Override the inherited languages (copied at creation; independent afterwards). |
| `--age TEXT` | `4-6` | Target age group. Drives prose complexity **and** PDF typography: `4-6` → short rhythmic sentences, 14 pt; `7+` → middle-grade, 12 pt; `12+` → young-adult prose, 9.5 pt. |
| `--idea TEXT` | empty | The book idea that seeds the outline (Step 01). The most important creative input. |
| `--spreads N` | `5` | Number of double-page spreads (1–30). Each spread = one text page + one image page. |

```bash
kb book new fritz --universe duesterwald --langs de,en --age 7+ --spreads 8 \
  --idea "Fritz gets lost in the Düsterwald at dusk and must find his way home before dark"
```

### `kb book list`

Table of all books: slug, title, universe, languages, page count.

### `kb book status <slug>`

Per-page pipeline progress: page number, status, available text languages, image path.

### `kb book show <slug> [--page N]`

Without `--page`: book metadata (title, universe, languages, age group, idea,
character/page counts).

| Flag | Description |
|---|---|
| `--page N` | Show one page in full: complete text in every language, the image prompt, characters present, and status. |

---

## 6. `kb run` — the generation pipeline

```
kb run <slug> [--force] [--recreate-images] [--from-page N] [--pages SPEC] [--interactive] [--temperature X]
```

Runs Steps 01–04: outline → story → character bible (one reference image per
character) → pages (bilingual text + illustrations, generated in parallel).

**Idempotent by default**: completed artifacts are skipped; an interrupted run
resumes exactly where it stopped; `approved` pages are never touched. Running
twice in a row does nothing the second time.

| Flag | Description |
|---|---|
| `--force` | Regenerate all **selected** artifacts regardless of status, including `approved` pages. Without page-selection flags this also regenerates outline, story, and bible. |
| `--recreate-images` | Regenerate images only; texts are kept. Without page-selection flags this includes the character **reference images** (redrawn first, then all page images are conditioned on them); with `--pages`/`--from-page` only the selected page images. Revokes approval on affected pages. |
| `--from-page N` | Restrict page-level work to pages numbered ≥ N. |
| `--pages SPEC` | Restrict to a page set. Grammar: comma-separated positive integers and inclusive ranges — `3`, `3,5`, `7-9`, `3,5,7-9`. Invalid specs are a usage error. |
| `--interactive` | Ask for confirmation before each pipeline step; declining aborts (exit 1). |
| `--temperature X` | LLM creativity for this run only (`0.0`–`1.0`); overrides `KB_LLM_TEMPERATURE`. |

Page-selection flags combine by **intersection**: `--from-page 3 --pages 1-4`
selects pages 3–4 only.

If some page images fail, the run finishes the remaining pages, prints a
summary, and exits 1 — re-running retries only the failed pages.

**Content-safety refusals.** If the image provider's safety filter refuses a
scene (e.g. Gemini `finishReason: IMAGE_SAFETY` on graphic content), the
summary names the affected page(s) explicitly and marks them as *refused* —
retrying will **not** help. Soften that page's image instead:

```bash
kb edit <slug> --page N --image "symbolic and dreamlike, no gore, no graphic violence"
```

The instruction is appended to the original prompt, so the scene is kept but
defused. If the softened prompt is *still* refused (the original wording keeps
triggering the filter), replace the prompt entirely:

```bash
kb edit <slug> --page N --image-prompt "<a new, calmer description of the scene>"
```

Pages that failed for transient reasons (rate limits, network) are listed
separately with "re-run to retry".

## 7. `kb edit` — targeted changes

```
kb edit <slug> [--page N] [operation …]
```

All edits follow the page lifecycle (spec §6.2): editing revokes approval
automatically, so a stale page can never stay `approved`.

| Flag | Needs `--page` | Description |
|---|---|---|
| `--text TEXT` | yes | **LLM rewrite** of the page text in *all* languages at once, following your instruction (e.g. `"shorter and funnier"`, `"HARD LIMIT: 100 words per language"`). Languages stay in sync. |
| `--text-en TEXT` | yes | Manually replace the English text. |
| `--text-th TEXT` | yes | Manually replace the Thai text. |
| `--image TEXT` | yes | Regenerate the page image with the instruction appended to the original prompt. Character reference images are re-attached automatically. Also the fix for content-safety refusals — see §5. |
| `--image-prompt TEXT` | yes | **Replace** the page's image prompt entirely and regenerate. The escape hatch when the original scene keeps triggering the provider's safety filter even with a softening `--image` instruction. Mutually exclusive with `--image`. |
| `--bible TEXT` | no | Revise the character bible per instruction. Reference images are kept for characters whose identity is unchanged; use `kb run --recreate-images` to redraw. |
| `--approve-page N` | no | Mark a finished page as `approved` (allowed only from status `image_done`). Approved pages are protected from `kb run` unless `--force`. |
| `--temperature X` | no | LLM creativity for this edit only (`0.0`–`1.0`); overrides `KB_LLM_TEMPERATURE`. |

Operations can be combined in one call; they execute in the order: text
rewrite, manual text, image, bible, approval.

Page status lifecycle:

```
todo ──▶ text_done ──▶ image_done ──▶ approved
                ▲            ▲             │
                └── edits revoke approval ─┘
```

## 8. `kb pdf` — print-ready output

```
kb pdf <slug>
```

Renders `Books/<slug>/build/<slug>.pdf`: 216 × 216 mm pages (210 mm trim + 3 mm
bleed), verso text pages with proper gutters, recto full-bleed image pages,
fonts embedded from `Global/fonts/`, Thai line breaking via libthai. The HTML
intermediate is kept next to it for debugging. Requires all pages to have
images; fails with a clear message otherwise. Free and fast — re-render after
every edit.

## 9. `kb serve` / `kb open` — web editor

```
kb serve [--host TEXT] [--port N] [--temperature X]
```

Starts a local web UI with the same capabilities as `kb assistant`, laid out
as an always-visible accordion instead of a strict linear flow: every stage
of every book — including books that are already finished — stays open for
editing at any time, in any order.

| Command | Description |
|---|---|
| `kb serve [--host TEXT] [--port N] [--temperature X]` | Local web editor (default `http://127.0.0.1:8000`, Ctrl+C to stop). `--temperature` sets the initial LLM creativity; changeable any time in the page header. |
| `kb open <slug>` | Open a book in the host browser (start `kb serve` first). |

**What the browser can do — all backed by the same functions as the CLI:**

- Dashboard: every universe and book, with a progress badge per book (`kb book list` / `kb universe list` equivalent).
- Create universes and books (same fields as `kb universe new` / `kb book new`).
- Per book, an accordion: Universum → Buchidee → Outline → Story → Figurenbibel → Seiten → PDF.
  Each stage — even a finished one — can be reopened and edited: manually, or
  via a free-form instruction to the LLM, exactly like the corresponding
  `kb edit`/`kb assistant` action. Editing an upstream stage (concept,
  outline, story, bible) clears the now-stale downstream artifacts, same as
  `kb edit`/`kb run` (spec §6.2); the page asks for confirmation first.
  A "Weiter" button generates the next missing stage (equivalent to `kb run`
  for that step).
- Per page: approve, manually replace the text in every language, LLM
  rewrite, image edit (instruction appended), and image-prompt replace (the
  escape hatch for content-safety refusals) — the same five actions as
  `kb assistant`'s page review, individually addressable per page.
- Render the PDF, preview it inline, and download it (`kb pdf` equivalent).

LLM and image calls run as a single background job (one at a time, to keep
file writes race-free) so a request never blocks; the page shows a spinner
and refreshes automatically until the job is done, then shows the result.

**In Docker.** `docker compose up -d` starts the web editor **automatically**
(the container's default command is `kb serve --host 0.0.0.0`; `0.0.0.0` is
required so the published port is reachable, not the container-internal
`127.0.0.1`). Just open `http://127.0.0.1:8000` on the host — no extra `exec`
needed. `docker compose exec app kb ...` still works independently for
one-off CLI commands (it runs regardless of the server's own process).

**Security.** No authentication — this is a local, single-user tool by design
(spec §12), same as every other `kb` command. Do not expose the port beyond
your own machine or trusted network. Cross-site `POST` requests (e.g. from a
malicious page open in the same browser) are rejected with `403`.

---

## 10. Configuration (environment variables)

Set in the shell or in `.env` (loaded automatically; never committed). See
[.env.example](../.env.example) for the annotated template.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for real text generation. |
| `KB_LLM_PROVIDER` | `anthropic` | `anthropic` or `mock` (offline, deterministic, zero cost). |
| `KB_LLM_MODEL` | `claude-sonnet-4-5` | Anthropic model ID. Cheap development: `claude-haiku-4-5`. |
| `KB_LLM_TEMPERATURE` | provider default | LLM creativity, `0.0`–`1.0`: `0.0` = focused and reproducible, `1.0` = most varied. Applies to all text generation (outline, story, pages, edits). |
| `KB_IMAGE_PROVIDER` | `mock` | `mock` (placeholder gradients) or `imagen` (Google Gemini image models). |
| `KB_IMAGE_MODEL` | `gemini-3.1-flash-image` | Gemini image model. Higher quality: `gemini-3-pro-image`. |
| `GOOGLE_API_KEY` | — | Required for `imagen`. Get one at <https://aistudio.google.com/apikey>. |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Only for the optional Vertex AI route; not needed with `GOOGLE_API_KEY`. |
| `KB_MAX_CONCURRENCY` | `4` | Parallel image-generation requests. |
| `KB_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |

Zero-cost dry run of anything: `KB_LLM_PROVIDER=mock KB_IMAGE_PROVIDER=mock kb run <slug>`.

## 11. Book folder layout

```
Books/<slug>/
├── book.yaml          # book state (source of truth, minus pages)
├── pages/             # 001.yaml … one file per page (source of truth)
├── references/        # <character>.png — one reference image per character
├── images/            # page-001.png … page illustrations
├── views/             # generated Markdown (story.md, bible.md) — read-only views
└── build/             # HTML intermediate + final PDF — safe to delete
```

Everything is plain files; a book folder is self-contained and portable.
`views/` and `build/` are derived artifacts — regenerate them any time, never
edit them (changes are overwritten and ignored).

## 12. Recipes

```bash
# Full book from scratch (real providers)
kb assistant

# Non-interactive alternative
kb book new my-book --universe swiss-thai-myths --age 4-6 --spreads 8 --idea "…"
KB_IMAGE_PROVIDER=imagen kb run my-book
kb pdf my-book

# Own world & style for older readers
kb universe new my-world --langs en,th --style "cinematic ink and watercolor, realistic"
kb book new my-story --universe my-world --age 12-14 --spreads 10 --idea "…"

# Review loop
kb book show my-book --page 2                 # read
kb edit my-book --page 2 --text "less scary"  # optimize text (all languages)
kb edit my-book --page 2 --image "add rain"   # adjust the picture
kb pdf my-book                                # re-render (free)
kb edit my-book --approve-page 2              # lock the page

# Fix only what's broken
kb run my-book --recreate-images --pages 3,5-7
kb run my-book --force --pages 6              # full redo of one page
```
