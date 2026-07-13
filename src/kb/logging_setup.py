"""Logging setup: standard ``logging`` with Rich output (spec §10)."""

from __future__ import annotations

import logging

from rich.logging import RichHandler


def setup_logging(level: str) -> None:
    """Configure the root logger. ``level`` is validated by ``Settings.from_env``."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(show_path=False, rich_tracebacks=False)],
        force=True,
    )
    # Third-party libraries log verbosely at INFO; keep kb output readable.
    logging.getLogger("weasyprint").setLevel(logging.WARNING)
    logging.getLogger("weasyprint.progress").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("fontTools").setLevel(logging.WARNING)
