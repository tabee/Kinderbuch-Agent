---
description: "Use when writing or modifying Python source in src/ — pipeline steps, providers, models, persistence, CLI. Covers structured outputs, idempotency, atomic writes, retries, and provider patterns."
applyTo: "src/**/*.py"
---
# Python Implementation Guidelines

## Models & Persistence

- Pydantic v2 models per spec §6.1: `Book`, `Page`, `Character` with `slug` identifiers and `schema_version`.
- Paths stored in models are always relative to the book directory — book folders must stay portable.
- Every state write is atomic: serialize to a temp file in the target directory, then `os.replace` (HC-4.4). Persist page state immediately after each successful mutation.
- Page status machine (`todo → text_done → image_done → approved`) and edit/approval-revocation semantics follow spec §6.2 exactly.

## Structured LLM Outputs (HC-1.1)

- Every LLM call in Steps 01–04 constrains output to a Pydantic schema via native tool use or `instructor`.
- On validation failure: re-prompt with the validation errors appended, max 2 corrective attempts, then fail the step loudly. Never accept partially valid data.
- Never parse Markdown/free text into the domain model.

## Providers (HC-5.2/5.3)

- One ABC each for LLM and image providers; concrete classes selected via `KB_IMAGE_PROVIDER` etc. (spec §9).
- Credentials are read from environment variables inside concrete providers only. Validate config at instantiation; fail fast with an actionable message. Never log secrets or raw base64 payloads.
- The mock image provider must be fully functional offline (used by all tests).

## Concurrency & Resilience

- Step 04 image generation: `asyncio.gather` behind `asyncio.Semaphore(KB_MAX_CONCURRENCY)` (default 4). Per-page failure isolation — one failure never aborts siblings; summarize failures at the end and exit 1 (spec §7.3, §8.3).
- Wrap provider calls with tenacity: exponential backoff + jitter, max 5 attempts, retry only transient errors (429/5xx/network). Never retry 4xx auth/validation errors (spec §10).

## Visual Consistency (HC-2.x) — highest-priority code path

- Reference manager: at most one reference image per character present, hard cap 4 total; overflow resolved by `characters_present` salience order.
- Prompt builder: every prompt binds each reference index to a character name and spatial position; include per-character visual keywords to prevent reference bleed.

## Style

- Python 3.12 idioms, full type hints, concise docstrings on public APIs, composition over inheritance.
- CLI: Typer + Rich; exit codes per spec §8.3 (0 success, 1 runtime/partial failure, 2 usage error).
