---
description: "Use when editing the Dockerfile, docker-compose.yml, or container runtime dependencies. Covers the python:3.12-slim requirement and WeasyPrint/Thai system packages."
applyTo: "docker/**"
---
# Docker Guidelines

- Base image: `python:3.12-slim` (Debian bookworm). **Alpine is forbidden** (HC-3.3) — musl breaks Pango/libthai text shaping.
- Install the WeasyPrint/Thai runtime deps via apt: `libpango-1.0-0`, `libpangocairo-1.0-0`, `libcairo2`, `libthai0` (+ data), `libgdk-pixbuf-2.0-0`, `shared-mime-info`. Verify Thai rendering works in the built image before considering Docker work done.
- Do NOT install book fonts as system packages — content fonts come exclusively from the mounted `Global/fonts/` (HC-3.5).
- `docker compose up -d` is the single entry point; the developer works via `docker compose exec app kb ...`.
- `./Books` and `./Global` are bind mounts so generated files appear on the host immediately.
- No secrets baked into images or compose files; pass them via environment / `.env` (HC-5.3).
