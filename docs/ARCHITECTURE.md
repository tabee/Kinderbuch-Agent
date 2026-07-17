# kb — Architecture & Workflow

Rendered natively by GitHub (Mermaid). Companion documents: [MANUAL.md](MANUAL.md)
for every command/flag, [implementation-spec.md](../implementation-spec.md) for
requirements (HC-x.y).

## 1. Architecture — how the tool is built

```mermaid
flowchart TD
    USER([User]) --> CLI

    subgraph INTERFACE["Interface"]
        CLI["cli.py — Typer CLI<br/>exit codes 0/1/2 (§8.3)"]
        GUIDE["assistant.py — guided review gates<br/>manual + structured LLM revisions<br/>pause/resume from YAML"]
        WEB["web/app.py — FastAPI editor<br/>full parity with assistant.py<br/>accordion UI, any stage/book, any order<br/>localhost:8000"]
    end

    subgraph CORE["Core (src/kb/core)"]
        PIPE["pipeline.py<br/>orchestration, idempotency (HC-4.1)<br/>flag semantics (§8.2)"]
        subgraph STEPS["steps/"]
            S1["01 outline.py"]
            S2["02 story.py"]
            S3["03 bible.py<br/>1 reference/character (HC-2.1)"]
            S4["04 pages.py<br/>text + parallel images (§7.3)"]
            PROSE["prose.py<br/>age-aware guidance"]
        end
        EDIT["editing.py<br/>§6.2 lifecycle:<br/>text/rewrite/image/bible/approve"]
        BM["book_manager.py"]
        UM["universe_manager.py"]
        MODELS["models.py — Pydantic v2<br/>Book · Page · Character · Universe"]
        PERSIST["persistence.py<br/>atomic writes: tmp + os.replace (HC-4.4)"]
        VIEWS["views.py<br/>generated Markdown (HC-1.3)"]
    end

    subgraph CONSISTENCY["Consistency (HC-2.x)"]
        REFMGR["reference_manager.py<br/>≤1 ref/character, ≤4 total (HC-2.2)"]
        PROMPTB["prompt_builder.py<br/>spatial anchoring (HC-2.3)<br/>anti-bleed keywords (HC-2.4)"]
    end

    subgraph PROVIDERS["Providers — swappable ABCs (HC-5.2)"]
        LLMABC["llm/base.py<br/>LLMProvider ABC<br/>generate_structured (HC-1.1)"]
        ANTH["anthropic_provider.py<br/>tool-use + validation loop (§7.2)<br/>tenacity retries (§10)"]
        LLMMOCK["llm/mock.py<br/>deterministic, themed, offline"]
        IMGABC["image/base.py<br/>ImageProvider ABC<br/>ref-cap enforced (HC-2.2)"]
        GOOG["google_image.py<br/>Gemini generateContent<br/>reference-image parts"]
        IMGMOCK["image/mock.py<br/>gradient PNGs, offline"]
        CONFIG["config.py — env selection (§9)<br/>credentials only inside providers (HC-5.3)"]
    end

    subgraph OUTPUT["PDF (spec §11)"]
        RENDER["pdf/renderer.py<br/>age-aware typography"]
        TPL["templates/book.html.j2<br/>CSS Paged Media, bleed+gutter"]
        WEASY["WeasyPrint + Pango + libthai<br/>Thai line breaking (HC-3.4)"]
    end

    subgraph STATE["File state — no database (HC-4.3)"]
        BOOKS[("Books/&lt;slug&gt;/<br/>book.yaml · pages/*.yaml<br/>references/ · images/<br/>views/ · build/")]
        GLOBAL[("Global/<br/>universes/ · layouts/<br/>fonts/ (embedded, HC-3.5)")]
    end

    EXT_A[/"Anthropic API"/]
    EXT_G[/"Google Gemini API"/]

    CLI --> GUIDE & PIPE & EDIT & BM & UM & RENDER
    GUIDE --> PIPE & EDIT & BM & UM & RENDER
    WEB --> PIPE & EDIT & BM & UM & RENDER
    PIPE --> STEPS
    S1 & S2 & S4 --> PROSE
    STEPS --> LLMABC & IMGABC
    S4 --> REFMGR --> PROMPTB
    EDIT --> REFMGR & LLMABC & IMGABC
    CONFIG -.selects.-> LLMABC & IMGABC
    LLMABC --- ANTH & LLMMOCK
    IMGABC --- GOOG & IMGMOCK
    ANTH <--> EXT_A
    GOOG <--> EXT_G
    BM & UM --> MODELS
    BM --> PERSIST --> BOOKS
    STEPS --> VIEWS --> BOOKS
    UM --> GLOBAL
    RENDER --> TPL --> WEASY
    RENDER --> GLOBAL
    WEASY --> BOOKS
```

Key properties: all state is plain YAML/PNG under `Books/<slug>/` (portable,
diffable); every write is atomic; providers are selected via environment and
hold their own credentials; the mock providers make the entire pipeline run
offline at zero cost — that is what the test suite and phase gates use.

## 2. Workflow — from idea to printed book

```mermaid
flowchart TD
    IDEA([" Idea "]) --> NEW["kb book new &lt;slug&gt;<br/>--universe --age --spreads --idea"]
    IDEA --> GUIDE["kb assistant<br/>review each artifact<br/>manual or LLM revision"]
    UNI["kb universe new<br/>--style --langs"] -.optional, own world/style.-> NEW
    NEW --> RUN

    subgraph RUN["kb run — idempotent, resumable (HC-4.1)"]
        direction TB
        C1{"outline<br/>exists?"} -- no --> ST1["Step 01: Outline<br/>structured output (HC-1.1)"]
        C1 -- yes --> C2
        ST1 --> C2{"story<br/>exists?"}
        C2 -- no --> ST2["Step 02: Story<br/>one beat per spread<br/>age-aware prose"]
        C2 -- yes --> C3
        ST2 --> C3{"bible +<br/>refs exist?"}
        C3 -- no --> ST3["Step 03: Character Bible"]
        C3 -- yes --> ST4
        ST3 --> REFS["one reference image<br/>per character (HC-2.1)<br/>parallel, bounded"]
        REFS --> ST4

        subgraph ST4["Step 04: Pages — per page, persisted immediately"]
            direction TB
            TXT["bilingual text via LLM<br/>validation loop: ≤2 corrective<br/>re-prompts (§7.2)"]
            TXT --> SEL["select references:<br/>≤1 per character, ≤4 total,<br/>salience order (HC-2.2)"]
            SEL --> PB["build prompt:<br/>'X, matching reference image N,<br/>stands left…' (HC-2.3/2.4)"]
            PB --> IMG["generate images in parallel<br/>semaphore, failure-isolated (§7.3)"]
        end
    end

    ST4 --> REVIEW

    subgraph REVIEW["Review loop — per page (§6.2)"]
        direction TB
        SHOW["kb book show --page N<br/>read text + prompt"]
        SHOW --> DECIDE{ok?}
        DECIDE -- "text" --> ETXT["kb edit --text 'instruction'<br/>LLM rewrite, all languages"]
        DECIDE -- "picture" --> EIMG["kb edit --image 'instruction'<br/>regenerate with references"]
        DECIDE -- "cast" --> EBIB["kb edit --bible 'instruction'"]
        ETXT & EIMG & EBIB --> SHOW
        DECIDE -- "yes" --> APPROVE["kb edit --approve-page N<br/>locked against kb run"]
    end

    APPROVE --> PDF["kb pdf &lt;slug&gt;<br/>216×216mm, 3mm bleed, gutters<br/>embedded Noto fonts (HC-3.5)<br/>Thai via libthai (HC-3.4)"]
    REVIEW -.anytime, free.-> PDF
    PDF --> OUT([" print-ready PDF<br/>Books/&lt;slug&gt;/build/ "])
    GUIDE -.uses the same steps,<br/>page lifecycle, and renderer.-> OUT
    PREVIEW["kb serve<br/>web editor: same review actions as the<br/>assistant, any stage/book, any order"] -.-> REVIEW

    RETRY["interrupted / failed pages?<br/>just run kb run again —<br/>only missing work is redone"] -.-> RUN
```

Page lifecycle underlying the whole flow:

```mermaid
stateDiagram-v2
    [*] --> todo : page created from story beat
    todo --> text_done : Step 04 text
    text_done --> image_done : Step 04 image
    image_done --> approved : kb edit --approve-page
    approved --> image_done : any edit revokes approval
    image_done --> image_done : edit text / image
    note right of approved : protected from kb run unless --force
```
