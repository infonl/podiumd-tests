"""Unit tests for the load that runs while a component is broken."""

import threading

from podiumd_tests.chaos_load import Attempt
from podiumd_tests.chaos_load import Load
from podiumd_tests.chaos_load import failures
from podiumd_tests.chaos_load import recovery_seconds
from podiumd_tests.chaos_load import summary


def test_load_records_results_and_errors_of_every_call():
    done = threading.Event()
    calls = []

    def ok():
        calls.append("ok")
        return "zaak"

    def broken():
        calls.append("broken")
        done.set()
        msg = "refused"
        raise ConnectionError(msg)

    with Load({"ok": ok, "broken": broken}, workers=2, pause=0) as load:
        assert done.wait(5)
    names = {a.name for a in load.attempts}
    assert names == {"ok", "broken"}
    assert all(a.result == "zaak" and a.error is None for a in load.attempts if a.name == "ok")
    assert all(a.error == "ConnectionError: refused" for a in load.attempts if a.name == "broken")
    assert len(load.attempts) == len(calls)


def attempt(start, *, failed=False, seconds=1.0):
    return Attempt("kc_token", start, seconds, error="TokenError: 503" if failed else None)


def test_recovery_is_the_end_of_the_first_success_after_the_last_failure():
    attempts = [attempt(5), attempt(12, failed=True), attempt(20), attempt(30, failed=True), attempt(41), attempt(50)]
    assert recovery_seconds(attempts, since=10) == 32


def test_no_failure_after_since_is_no_outage_and_a_failing_end_is_no_recovery():
    assert recovery_seconds([attempt(5, failed=True), attempt(12)], since=10) == 0
    assert recovery_seconds([attempt(12), attempt(20, failed=True)], since=10) is None


def test_failures_and_summary_name_each_call():
    attempts = [attempt(12, failed=True), attempt(20)]
    assert failures(attempts, since=10) == ["kc_token at +2s: TokenError: 503"]
    assert summary(attempts) == "kc_token 2 (1 failed)"
