---
description: "Implement one phase of the Kinderbuch Agent per implementation-spec.md, with HC verification and quality gates"
argument-hint: "Phase number (1-4)"
agent: "agent"
---
Implement the requested phase of the Kinderbuch Agent, exactly as specified in [implementation-spec.md](../../implementation-spec.md).

Process:

1. Re-read the spec sections relevant to this phase (§15 defines phase scope and its verification gate) and the Hard Constraints (§3).
2. Report which spec sections and HC IDs the phase touches before writing code.
3. Implement the phase. Reference HC IDs in comments and test names where relevant.
4. Implement the phase's verification gate (§15) as offline pytest tests using the mock providers (`KB_LLM_PROVIDER=mock`, `KB_IMAGE_PROVIDER=mock`) — zero network access, zero API cost. All earlier phase gates must remain green.
5. Run the quality gates and fix all findings:
   - `uv run ruff check .` and `uv run ruff format .`
   - `uv run mypy src/`
   - `uv run pytest` (offline, mock providers only — includes all phase gates)
6. Self-review against every HC the phase touches; list each one with a pass/fail verdict and evidence (file + line or test name).
7. Present a short completion report: what was built, the gate test results, deliberate deviations with rationale, and open questions.

Phase 1 only: additionally present `tree -L 3` and `kb --help` output, then STOP and wait for human review (spec §15 exit criterion). Never begin a later phase without explicit approval.
