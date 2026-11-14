"""Load that keeps running while a component is broken, and what each of its calls saw."""

from __future__ import annotations

import threading
import time

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import cycle
from itertools import islice
from typing import TYPE_CHECKING

from podiumd_tests.background import running
from podiumd_tests.config import REPO_ROOT
from podiumd_tests.perf.availability import availability_limits
from podiumd_tests.perf.availability import watched
from podiumd_tests.perf.availability_report import report

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator
    from collections.abc import Mapping
    from collections.abc import Sequence

    from podiumd_tests.environment import Environment
    from podiumd_tests.perf.availability import Watch


# The load's calls by name.
type Calls = Mapping[str, Callable[[], object]]


@dataclass(frozen=True)
class Attempt:
    """One call of the load: when it started (epoch seconds), how long it took, and its result or error."""

    name: str
    start: float
    seconds: float
    result: object = None
    error: str | None = None

    @property
    def end(self) -> float:
        """Return when the call ended (epoch seconds)."""
        return self.start + self.seconds


class Load:
    """Calls made in turn on worker threads, `pause` seconds apart, and what each of them saw."""

    def __init__(self, calls: Calls, pause: float) -> None:
        self.calls: Calls = calls
        self.pause: float = pause
        self.stopped: threading.Event = threading.Event()
        self._lock: threading.Lock = threading.Lock()
        self._attempts: list[Attempt] = []

    @property
    def attempts(self) -> list[Attempt]:
        """Return the calls made so far, in the order they ended."""
        with self._lock:
            return list(self._attempts)

    def run_for(self, seconds: float) -> None:
        """Let the load run for this long."""
        self.stopped.wait(seconds)

    def work(self, index: int) -> None:
        """Make the calls until stopped, starting at call `index`."""
        for name in islice(cycle(self.calls), index, None):
            if self.stopped.is_set():
                return
            started, clock = time.time(), time.monotonic()
            result: object = None
            error: str | None = None
            try:
                result = self.calls[name]()
            except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # a failure is a result
                error = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._attempts.append(Attempt(name, started, time.monotonic() - clock, result, error))
            self.stopped.wait(self.pause)


@contextmanager
def loaded(calls: Calls, *, workers: int, pause: float) -> Generator[Load]:
    """Run the calls on `workers` threads while the block runs; each worker starts at another call."""
    load = Load(calls, pause)
    threads = [threading.Thread(target=load.work, args=(index,), daemon=True) for index in range(workers)]

    def stop() -> None:
        load.stopped.set()
        for thread in threads:
            thread.join()

    with running(threads, stop):
        yield load


@contextmanager
def watched_load(
    env: Environment, served: Sequence[str], calls: Calls, *, workers: int, pause: float
) -> Generator[tuple[Load, Watch]]:
    """Run the calls as `loaded` does while perf.yaml's availability gate watches the components that serve them."""
    limits = availability_limits(REPO_ROOT / "perf.yaml")
    # watched measures the recovery after its block; a block that raises needs no recovery measured.
    gate = watched(env, served, limits)
    with gate as watch, loaded(calls, workers=workers, pause=pause) as load:  # pylint: disable=contextmanager-generator-missing-cleanup
        yield load, watch


def load_report(load: Load, watch: Watch, since: float) -> str:
    """Return the Markdown report of the load: its calls, each failed call, and the availability gate's report."""
    failed = "\n".join(f"- {line}" for line in failures(load.attempts, since))
    calls = f"Calls: {summary(load.attempts)}."
    return "\n\n".join(part for part in (calls, failed, report(watch, "")) if part)


def failures(attempts: Sequence[Attempt], since: float) -> list[str]:
    """Return one line per failed call: its name, start in seconds after `since`, and its error."""
    failed = (attempt for attempt in attempts if attempt.error is not None)
    return [f"{attempt.name} at +{attempt.start - since:.0f}s: {attempt.error}" for attempt in failed]


def recovery_seconds(attempts: Sequence[Attempt], since: float) -> float | None:
    """Return the seconds from `since` until the end of the first call that succeeded after every failed one.

    0 when no call that started after `since` failed; None when the last call failed.
    """
    later = sorted((attempt for attempt in attempts if attempt.start >= since), key=_start)
    failed = [attempt.start for attempt in later if attempt.error is not None]
    if not failed:
        return 0
    after = (attempt for attempt in later if attempt.start > failed[-1])
    recovered = [attempt.end for attempt in after if attempt.error is None]
    return recovered[0] - since if recovered else None


def summary(attempts: Sequence[Attempt]) -> str:
    """Return the calls and failures per call name, e.g. "kc_token 40 (3 failed)"."""
    calls = Counter(attempt.name for attempt in attempts)
    failed = Counter(attempt.name for attempt in attempts if attempt.error is not None)
    lines = [f"{name} {calls[name]} ({failed[name]} failed)" for name in sorted(calls)]
    return ", ".join(lines)


def _start(attempt: Attempt) -> float:
    return attempt.start
