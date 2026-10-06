"""Unit tests for wait_until."""

import pytest

from podiumd_tests.wait import Clock
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_returns_the_first_truthy_value():
    clock = FakeClock()
    values = iter([None, [], {"id": 1}])
    result = wait_until(
        lambda: next(values), timeout=10, interval=1, description="zaak", clock=Clock(clock, clock.sleep)
    )
    assert result == {"id": 1}
    assert clock.now == 2


def test_exceptions_count_as_not_yet_and_are_reported():
    clock = FakeClock()

    def probe():
        msg = "refused"
        raise ConnectionError(msg)

    with pytest.raises(WaitTimeoutError, match="waiting for webhook; last attempt ConnectionError: refused"):
        wait_until(probe, timeout=3, interval=1, description="webhook", clock=Clock(clock, clock.sleep))


def test_is_an_assertion_error_for_pytest():
    assert issubclass(WaitTimeoutError, AssertionError)
