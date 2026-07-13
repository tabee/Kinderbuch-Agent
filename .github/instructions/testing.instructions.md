---
description: "Use when writing or modifying tests. Covers offline-only policy, mock providers, and the mandatory critical-path coverage from spec §13."
applyTo: "tests/**"
---
# Testing Guidelines

- Framework: pytest. Tests MUST run offline — no network access; use the mock LLM/image providers exclusively.
- Use `tmp_path` for all file-system state; never touch the real `Books/` or `Global/` directories.
- Name tests after the requirement they verify where sensible, e.g. `test_hc22_reference_cap_four_characters`.

## Mandatory coverage (spec §13)

1. Reference selection for multi-character scenes (HC-2.2), including the > 4-character cap and salience ordering.
2. Language inheritance from Universe to Book (copied at creation, independent afterwards).
3. Idempotency and status transitions: default skip behavior, `--force`, `--recreate-images`, edit/approval-revocation semantics (spec §6.2, §8.2).
4. `--pages` spec parsing (`3,5,7-9`), including invalid inputs → usage error (exit code 2).
5. Atomic persistence round-trip: Book/Page → YAML → Book/Page, plus `schema_version` rejection of newer versions.
