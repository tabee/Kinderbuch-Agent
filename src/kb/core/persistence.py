"""Atomic file persistence: temp file in the target directory + ``os.replace`` (HC-4.4)."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any, cast

import yaml

from kb.errors import KBError


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically; a killed process never corrupts state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping; anything else is a corrupt state file."""
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise KBError(f"expected a YAML mapping in {path}")
    return cast("dict[str, Any]", data)
