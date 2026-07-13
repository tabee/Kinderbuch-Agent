---
description: "Use when working on PDF generation, HTML/CSS page templates, WeasyPrint, fonts, Thai typesetting, or print layout. Covers bleed, gutters, page geometry, and libthai requirements."
applyTo: ["src/pdf/**", "Global/layouts/**", "Global/fonts/**"]
---
# PDF & Thai Typesetting Guidelines

Full requirements: spec §11 and HC-3.x. This is a critical path — correctness beats cleverness.

## Geometry (spec §11.1)

- Default layout: 210 × 210 mm trim, 3 mm bleed all sides → 216 × 216 mm media box.
- Text pages: inner (gutter) margin ≥ 20 mm, other margins ≥ 12 mm, no text within 5 mm of trim.
- Image pages: illustration fills the full bleed box.
- Use CSS Paged Media: `@page` size includes bleed; distinguish left/right pages (`@page :left` / `:right`) for gutter placement.

## Page Structure (HC-3.1)

- Verso (left) = text only; recto (right) = full-bleed image. Never combine text and image on one page.
- Minimal title page allowed as front matter. Set PDF metadata (title, primary language).

## Thai Text (HC-3.4)

- Wrap Thai content in elements with `lang="th"`.
- Font-family Noto Sans Thai. Do NOT use `word-break` — WeasyPrint ignores it; Pango + libthai perform Thai line segmentation natively (verified).
- Line breaking relies on Pango + libthai — these come from the Docker image. If Thai breaks mid-word, check libthai is installed and `lang` attributes are set; do not hack around it with manual breaks.

## Fonts (HC-3.5)

- All fonts loaded via `@font-face` from `Global/fonts/` (Noto Sans, Noto Sans Thai) and embedded in the PDF.
- Never rely on system fonts for book content — output must be byte-deterministic across environments.

## Rendering

- WeasyPrint + Jinja2 templates. Keep HTML intermediates in `Books/<slug>/build/` for debugging; they are disposable.
- RGB workflow; no CMYK/ICC handling (spec §1.3, §11.4).
