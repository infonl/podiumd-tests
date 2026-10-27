"""Polling with a deadline instead of fixed sleeps; durations."""

from __future__ import annotations

import re
import time

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


DURATION = re.compile(r"(?:\d+[smhd])+")
_PART = re.compile(r"(\d+)([smhd])")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_duration(text: str) -> timedelta:
    """A duration such as 30s, 1m30s, 24h or 7d (Prometheus format); ValueError otherwise."""
    if not DURATION.fullmatch(text.strip()):
        msg = f"duration {text!r}: expected numbers with s, m, h or d, e.g. 24h"
        raise ValueError(msg)
    return sum((timedelta(**{_UNITS[unit]: int(n)}) for n, unit in _PART.findall(text)), timedelta())


class WaitTimeoutError(AssertionError):
    """The condition did not become true in time. An AssertionError, so pytest reports it as a test failure."""


@dataclass(frozen=True)
class Clock:
    """Time source for wait_until; unit tests pass a fake one."""

    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def wait_until[T](
    probe: Callable[[], T | None],
    *,
    timeout: float,
    interval: float = 2.0,
    description: str,
    clock: Clock | None = None,
) -> T:
    """Call probe until it returns a truthy value and return that value.

    Exceptions from probe count as "not yet"; the last one is reported on timeout.
    """
    clock = clock or Clock()
    deadline = clock.now() + timeout
    last: str = "no attempt made"
    while True:
        try:
            value = probe()
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # any failure means "not yet"
            last = f"{type(exc).__name__}: {exc}"
        else:
            if value:
                return value
            last = f"returned {value!r}"
        if clock.now() >= deadline:
            msg = f"timed out after {timeout:g}s waiting for {description}; last attempt {last}"
            raise WaitTimeoutError(msg)
        clock.sleep(interval)
