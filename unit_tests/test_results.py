"""Unit tests for run directories, junit parsing and result files."""

import json

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from podiumd_tests.credentials import Redactor
from podiumd_tests.results import LocalDirSink
from podiumd_tests.results import RunInfo
from podiumd_tests.results import parse_junit
from podiumd_tests.results import run_dir
from podiumd_tests.results import run_tag
from podiumd_tests.results import write_run

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
  <testcase classname="tests.smoke.test_up" name="test_ok"/>
  <testcase classname="tests.smoke.test_up" name="test_bad"><failure message="assert 500 == 200&#10;more"/></testcase>
  <testcase classname="tests.smoke.test_up" name="test_err"><error message="fixture failed"/></testcase>
  <testcase classname="tests.smoke.test_up" name="test_skip"><skipped type="pytest.skip" message="requires: oab"/></testcase>
  <testcase classname="tests.smoke.test_up" name="test_known"><skipped type="pytest.xfail" message="TICKET-1"/></testcase>
</testsuite></testsuites>
"""


def test_run_dir_uses_utc_month_partition_and_underscores():
    started = datetime(2026, 10, 1, 1, 30, 5, tzinfo=timezone(timedelta(hours=2)))
    assert run_dir(started, "ontw-icat", "smoke", "a1b2c3") == "2026-09/20260930-233005_ontw-icat_smoke_a1b2c3"


def test_parse_junit_counts_every_outcome():
    counts, failures = parse_junit(JUNIT)
    assert (counts.passed, counts.failed, counts.errors, counts.skipped, counts.xfailed, counts.total) == (
        1,
        1,
        1,
        1,
        1,
        5,
    )
    assert [f.message for f in failures] == ["assert 500 == 200", "fixture failed"]
    assert failures[0].test_id == "tests.smoke.test_up::test_bad"


def test_write_run_redacts_secrets(tmp_path):
    redactor = Redactor()
    redactor.add("super-secret-token")
    info = RunInfo(
        run_id="a1b2c3",
        env="kees00",
        tier="smoke",
        started=datetime.now(UTC).isoformat(),
        finished=datetime.now(UTC).isoformat(),
        exit_code=1,
        selection=["--token=super-secret-token"],
        suite_commit="abc1234",
    )
    counts, failures = parse_junit(JUNIT)
    info.counts = counts
    write_run(LocalDirSink(tmp_path), "2026-10/run", info, failures, redactor)
    run_json = (tmp_path / "2026-10/run/run.json").read_text()
    summary = (tmp_path / "2026-10/run/summary.md").read_text()
    assert "super-secret-token" not in run_json + summary
    assert json.loads(run_json)["counts"]["failed"] == 1
    assert "| 1 | 1 | 1 | 1 | 1 | 5 |" in summary


def test_run_tag_marks_resources_of_a_run():
    assert run_tag("a1b2c3") == "ptest-a1b2c3"
