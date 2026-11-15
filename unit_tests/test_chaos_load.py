"""Unit tests for the load that runs while a component is broken."""

import threading

from podiumd_tests.chaos_load import Attempt
from podiumd_tests.chaos_load import Load
from podiumd_tests.chaos_load import failures
from podiumd_tests.chaos_load import load_report
from podiumd_tests.chaos_load import loaded
from podiumd_tests.chaos_load import p95_ms
from podiumd_tests.chaos_load import recovery_seconds
from podiumd_tests.chaos_load import slowdown
from podiumd_tests.chaos_load import summary
from podiumd_tests.perf.availability import Limits
from podiumd_tests.perf.availability import Watch


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

    with loaded({"ok": ok, "broken": broken}, workers=2, pause=0) as load:
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


def test_load_report_names_the_calls_the_failures_and_the_gate():
    done = threading.Event()

    def broken():
        done.set()
        msg = "refused"
        raise ConnectionError(msg)

    with loaded({"broken": broken}, workers=1, pause=0) as load:
        assert done.wait(5)
    watch = Watch(
        frozenset(("openzaak",)), Limits(5, 60, 0.99, 0.9, 300, 1), started=1_800_000_000, ended=1_800_000_060
    )
    lines = load_report(load, watch, since=load.attempts[0].start).splitlines()
    assert lines[0].startswith("Calls: broken ")
    assert lines[2] == "- broken at +0s: ConnectionError: refused"
    assert "Load 08:00:00-08:01:00 UTC; not all Ready again." in lines


def test_p95_counts_only_the_calls_that_succeeded():
    durations = [attempt(0, seconds=n / 1000) for n in range(1, 101)]
    assert round(p95_ms([*durations, attempt(0, failed=True, seconds=60)])) == 95


def test_slowdown_compares_the_p95_after_with_perf_yamls_limit_against_the_p95_before():
    calls = [attempt(0, seconds=0.1), attempt(1, seconds=0.1), attempt(10, seconds=0.5), attempt(11, seconds=0.5)]
    before, after, limit = slowdown([*calls, Attempt("other", 12, 9.0)], 5, "kc_token")
    assert (round(before), round(after)) == (100, 500)
    # perf.yaml's defaults: 1.5 times, and at least 200 ms more.
    assert limit == 300


def test_created_lists_the_urls_the_successful_calls_returned_since(monkeypatch):
    attempts = [
        Attempt("create", 1, 1, {"url": "z/1"}),
        Attempt("create", 2, 1, error="ConnectionError: refused"),
        Attempt("create", 3, 1, {"url": "z/3"}),
        Attempt("read", 4, 1, [{"url": "p/1"}]),
    ]
    monkeypatch.setattr(Load, "attempts", property(lambda _load: attempts))
    load = Load({}, pause=0)
    assert load.created(name="create") == ["z/1", "z/3"]
    assert load.created(since=2, name="create") == ["z/3"]
