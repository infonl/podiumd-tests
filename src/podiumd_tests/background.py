"""Threads that run while a with-block runs."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading

    from collections.abc import Callable
    from collections.abc import Generator
    from collections.abc import Sequence


@contextmanager
def running(threads: Sequence[threading.Thread], stop: Callable[[], None]) -> Generator[None]:
    """Start the threads for the block; call stop afterwards, also when the block raises."""
    for thread in threads:
        thread.start()
    try:
        yield
    finally:
        stop()
