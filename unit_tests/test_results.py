"""Unit tests for run directories, junit parsing and result files."""

import json

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from podiumd_tests.credentials import Redactor
from podiumd_tests.results import Details
from podiumd_tests.results import Entry
from podiumd_tests.results import LocalDirSink
from podiumd_tests.results import RunInfo
from podiumd_tests.results import known_defects
from podiumd_tests.results import parse_junit
from podiumd_tests.results import run_dir
from podiumd_tests.results import run_tag
from podiumd_tests.results import summary_markdown
from podiumd_tests.results import write_run

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
  <testcase classname="tests.smoke.test_up" name="test_ok"/>
  <testcase classname="tests.smoke.test_up" name="test_bad"><failure message="assert 500 == 200&#10;more"/></testcase>
  <testcase classname="tests.smoke.test_up" name="test_err"><error message="fixture failed"/></testcase>
  <testcase classname="tests.smoke.test_up" name="test_skip"><skipped type="pytest.skip" message="requires: oab"/></testcase>
  <testcase classname="tests.smoke.test_up" name="test_known">
    <properties><property name="source" value="TA regression/1-x.spec.ts: why"/></properties>
    <skipped type="pytest.xfail" message="TICKET-1"/></testcase>
  <testcase classname="tests.smoke.test_up" name="test_fixed">
    <properties><property name="xpass" value="TICKET-2"/></properties></testcase>
</testsuite></testsuites>
"""


def test_run_dir_uses_utc_month_partition_and_underscores():
    started = datetime(2026, 10, 1, 1, 30, 5, tzinfo=timezone(timedelta(hours=2)))
    assert run_dir(started, "ontw-icat", "smoke", "a1b2c3") == "2026-09/20260930-233005_ontw-icat_smoke_a1b2c3"


def test_parse_junit_counts_every_outcome():
    counts, details = parse_junit(JUNIT)
    found = (counts.passed, counts.failed, counts.errors, counts.skipped, counts.xfailed, counts.xpassed)
    assert (*found, counts.total) == (1, 1, 1, 1, 1, 1, 6)
    assert [f.message for f in details.failures] == ["assert 500 == 200", "fixture failed"]
    assert details.failures[0].test_id == "tests.smoke.test_up::test_bad"
    assert [(e.test_id, e.message) for e in details.xpassed] == [("tests.smoke.test_up::test_fixed", "TICKET-2")]
    assert [e.message for e in details.xfailed + details.skipped] == ["TICKET-1", "requires: oab"]
    assert details.xfailed[0].sources == ["TA regression/1-x.spec.ts: why"]


def test_known_defects_lists_reports_whose_defect_did_not_show_first():
    details = Details(
        xfailed=[
            Entry("t1", "[open-zaak-1] Open Zaak answers 500"),
            Entry("t2", "[kiss-1] KISS 500"),
            Entry("t3", "[kiss-1] KISS 500"),
            Entry("t4", "untagged reason"),
        ],
        xpassed=[Entry("t5", "[kiss-1] KISS 500")],
        failures=[Entry("t6", "[XPASS(strict)] [zac-4] ZAC unready"), Entry("t7", "assert 500 == 200")],
    )
    assert known_defects(details) == [
        "| kiss-1 | **did not show in 1 of 3 tests** | 3 |",
        "| zac-4 | **did not show** | 1 |",
        "| no report id | still fails | 1 |",
        "| open-zaak-1 | still fails | 1 |",
    ]
    assert known_defects(Details()) == []


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
    counts, details = parse_junit(JUNIT)
    info.counts = counts
    info.versions = {"ita": "3.3.4"}
    write_run(LocalDirSink(tmp_path), "2026-10/run", info, details, redactor)
    run_json = (tmp_path / "2026-10/run/run.json").read_text()
    summary = (tmp_path / "2026-10/run/summary.md").read_text()
    assert "super-secret-token" not in run_json + summary
    assert json.loads(run_json)["counts"]["failed"] == 1
    assert "| 1 | 1 | 1 | 1 | 1 | 1 | 6 |" in summary
    assert "- Component versions: ita 3.3.4" in summary
    assert "- TICKET-2 (1): `tests.smoke.test_up::test_fixed`" in summary
    assert "| no report id | **did not show in 1 of 2 tests** | 2 |" in summary
    assert "- requires: oab (1): `tests.smoke.test_up::test_skip`" in summary


def test_run_tag_marks_resources_of_a_run():
    assert run_tag("a1b2c3") == "ptest-a1b2c3"


def test_summary_lists_the_sources_of_known_defect_tests():
    details = Details(xfailed=[Entry("t1", "[kiss-1] KISS 500", ["TA regression/1-x.spec.ts: why"])])
    info = RunInfo("r", "e", "full", "s", "f", 0, [], "c")
    assert "- `t1`: TA regression/1-x.spec.ts: why" in summary_markdown(info, details)
