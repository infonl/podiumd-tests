"""Load that keeps running while a component is broken, and what each of its calls saw."""

from __future__ import annotations

import threading
import time

from collections import Counter
from dataclasses import dataclass
from itertools import cycle
from itertools import islice
from typing import TYPE_CHECKING
from typing import Self

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping
    from collections.abc import Sequence


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
    """Call each of `calls` in turn on `workers` threads, `pause` seconds apart, while the block runs."""

    def __init__(self, calls: Mapping[str, Callable[[], object]], *, workers: int, pause: float) -> None:
        self.calls: Mapping[str, Callable[[], object]] = calls
        self.pause: float = pause
        self._stop: threading.Event = threading.Event()
        self._lock: threading.Lock = threading.Lock()
        self._attempts: list[Attempt] = []
        self._threads: list[threading.Thread] = [
            threading.Thread(target=self._work, args=(index,), name=f"load-{index}", daemon=True)
            for index in range(workers)
        ]

    def __enter__(self) -> Self:
        """Start the workers."""
        for thread in self._threads:
            thread.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        """Let each worker finish its call, then stop."""
        self._stop.set()
        for thread in self._threads:
            thread.join()

    @property
    def attempts(self) -> list[Attempt]:
        """Return the calls made so far, in the order they ended."""
        with self._lock:
            return list(self._attempts)

    def run_for(self, seconds: float) -> None:
        """Let the load run for this long."""
        self._stop.wait(seconds)

    def _work(self, index: int) -> None:
        # Each worker starts at another call, so all calls run from the start.
        for name in islice(cycle(self.calls), index, None):
            if self._stop.is_set():
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
            self._stop.wait(self.pause)


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
