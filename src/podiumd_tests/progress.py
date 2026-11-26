"""A run's progress file: one line per finished test, written while the run goes on."""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence
    from pathlib import Path


# (phase, pytest's outcome of the phase, xfail marker) -> the test's outcome; other phases settle nothing.
OUTCOMES = {
    ("setup", "failed", False): "error",
    ("setup", "failed", True): "error",
    ("setup", "skipped", False): "skipped",
    ("setup", "skipped", True): "xfailed",
    ("call", "passed", False): "passed",
    ("call", "passed", True): "xpassed",
    ("call", "failed", False): "failed",
    ("call", "failed", True): "failed",
    ("call", "skipped", False): "skipped",
    ("call", "skipped", True): "xfailed",
    ("teardown", "failed", False): "error in teardown",
    ("teardown", "failed", True): "error in teardown",
}


def outcome(report: pytest.TestReport) -> str | None:
    """Return the test's outcome this report settles, or None when another phase settles it."""
    return OUTCOMES.get((report.when, report.outcome, hasattr(report, "wasxfail")))


def _now() -> str:
    return time.strftime("%H:%M:%S")


class Progress:
    """pytest plugin that appends one line per finished test: time, count, outcome, test id and duration."""

    def __init__(self, path: Path, clock: Callable[[], str] = _now) -> None:
        self._path: Path = path
        self._clock: Callable[[], str] = clock
        self._total: int | None = None
        self._done: int = 0

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        """Record the test count of a run without xdist."""
        self._collected(len(session.items))

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, ids: Sequence[str]) -> None:  # noqa: WPS118  # xdist's hook name
        """Record the test count from an xdist worker's collection; every worker has the same tests."""
        self._collected(len(ids))

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Write the line of the test this report settles; the xdist controller gets every worker's reports."""
        result = outcome(report)
        if result is None:
            return
        if result != "error in teardown":  # its call already counted the test
            self._done += 1
        total = "?" if self._total is None else self._total
        self._write(f"{self._done}/{total} {result} {report.nodeid} ({report.duration:.1f}s)")

    def _collected(self, total: int) -> None:
        if self._total is None:
            self._total = total
            self._write(f"collected {total} tests")

    def _write(self, line: str) -> None:
        # Opened per line, so a reader sees each finished test at once.
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(f"{self._clock()} {line}\n")
