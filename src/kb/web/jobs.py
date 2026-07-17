"""Single-slot background job runner for the web editor (spec §12).

The web UI is a local, single-user tool over plain YAML files (HC-4.3); running
two mutations at once could race on the same writes, so at most one job runs at
a time — a second start is rejected rather than queued. Jobs are used only for
LLM/image calls (§7.2/§7.3), which can take seconds; everything else (manual
edits, approvals, PDF rendering) is fast enough to run synchronously.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Job:
    """State of one background action, keyed by book or universe slug."""

    slug: str
    description: str
    done: bool = False
    error: str | None = None


class JobRunner:
    """Runs at most one background job at a time; not shared across processes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._job: Job | None = None

    @property
    def current(self) -> Job | None:
        return self._job

    def start(self, slug: str, description: str, target: Callable[[], None]) -> Job | None:
        """Start a background job; returns ``None`` if one is already running."""
        with self._lock:
            if self._job is not None and not self._job.done:
                return None
            job = Job(slug=slug, description=description)
            self._job = job

        def run() -> None:
            try:
                target()
            except Exception as exc:
                job.error = str(exc)
            finally:
                job.done = True

        threading.Thread(target=run, daemon=True).start()
        return job

    def clear(self, job: Job) -> None:
        """Drop a finished job once its result has been shown (one-shot flash)."""
        with self._lock:
            if self._job is job:
                self._job = None
