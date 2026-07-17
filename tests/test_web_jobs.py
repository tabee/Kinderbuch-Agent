"""Unit tests for the single-slot background job runner (spec §12)."""

from __future__ import annotations

import threading
import time

from kb.web.jobs import JobRunner


def test_start_runs_target_and_marks_done() -> None:
    runner = JobRunner()
    calls: list[str] = []

    job = runner.start("demo", "doing work …", lambda: calls.append("ran"))
    assert job is not None
    assert job.slug == "demo"
    assert job.description == "doing work …"

    time.sleep(0.2)  # let the daemon thread run
    assert calls == ["ran"]
    assert job.done is True
    assert job.error is None


def test_start_rejects_a_second_job_while_one_is_running() -> None:
    runner = JobRunner()
    release = threading.Event()
    started = threading.Event()

    def slow() -> None:
        started.set()
        release.wait(2.0)

    first = runner.start("demo", "slow work", slow)
    assert first is not None
    started.wait(2.0)

    second = runner.start("demo", "other work", lambda: None)
    assert second is None  # rejected: one job already in flight

    release.set()  # let the first job's thread finish
    time.sleep(0.05)


def test_start_accepts_a_new_job_once_the_previous_one_is_done() -> None:
    runner = JobRunner()
    first = runner.start("demo", "first", lambda: None)
    assert first is not None
    time.sleep(0.2)
    assert first.done is True

    second = runner.start("demo", "second", lambda: None)
    assert second is not None
    assert second is not first


def test_exception_in_target_is_captured_as_job_error() -> None:
    runner = JobRunner()

    def boom() -> None:
        raise ValueError("something went wrong")

    job = runner.start("demo", "failing work", boom)
    assert job is not None
    time.sleep(0.2)
    assert job.done is True
    assert job.error == "something went wrong"


def test_clear_only_removes_the_matching_job() -> None:
    runner = JobRunner()
    job = runner.start("demo", "work", lambda: None)
    assert job is not None
    time.sleep(0.2)

    other_job = runner.start("other", "unrelated", lambda: None)
    assert other_job is not None
    time.sleep(0.2)

    runner.clear(job)  # job is stale (already replaced by other_job); no-op
    assert runner.current is other_job

    runner.clear(other_job)
    assert runner.current is None
