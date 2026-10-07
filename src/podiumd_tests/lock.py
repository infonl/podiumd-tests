"""A lock file shared with other agents working on the same environment (profile settings.lock_file).

One line per holder: "<who> <what> <ISO start time>". Taken exclusively (O_EXCL), removed afterwards.
"""

from __future__ import annotations

import os

from contextlib import contextmanager
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

HOLDER = "podiumd-tests"


class LockBusyError(Exception):
    """Another agent holds the lock; the message names it."""


@contextmanager
def held(path: str | None, what: str) -> Generator[None]:
    """Hold the lock file while the block runs; no-op without a path."""
    if not path:
        yield
        return
    lock = Path(path)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        holder = lock.read_text(encoding="utf-8").strip() or "unknown"
        msg = f"{lock} is held by: {holder}; wait or ask its owner"
        raise LockBusyError(msg) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"{HOLDER} {what} {datetime.now(tz=UTC).isoformat(timespec='seconds')}\n")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)
