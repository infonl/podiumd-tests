"""Unit tests for threads that run during a block."""

import threading

import pytest

from podiumd_tests.background import running


class LoadFailedError(RuntimeError):
    """The block's load failed."""


def run_failing_load(thread, stopped):
    with running([thread], stopped):
        assert thread.is_alive()
        raise LoadFailedError


def test_running_starts_the_threads_and_stops_them_when_the_block_raises():
    stop = threading.Event()
    thread = threading.Thread(target=stop.wait, daemon=True)

    def stopped():
        stop.set()
        thread.join()

    with pytest.raises(LoadFailedError):
        run_failing_load(thread, stopped)
    assert not thread.is_alive()
