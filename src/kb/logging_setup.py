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
