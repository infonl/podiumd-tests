"""Run results under results/<YYYY-MM>/<timestamp>_<env>_<tier>_<runid>/.

All writing goes through a ResultsSink, so another storage needs no caller changes.
"""

from __future__ import annotations

import json
import re
import secrets

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from itertools import chain
from typing import TYPE_CHECKING
from typing import Protocol

# Parses only the junit.xml written by our own pytest run.
from xml.etree import ElementTree as ET  # nosec B405

from podiumd_tests.process import ProcessError
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process

if TYPE_CHECKING:
    from pathlib import Path

    from podiumd_tests.credentials import Redactor


class ResultsSink(Protocol):
    """Where run results are written."""

    def write_text(self, relative_path: str, content: str) -> None:
        """Write one text file at a path relative to the sink root."""
        ...

    def location(self, relative_path: str) -> str:
        """Human-readable location of a relative path (a file path for LocalDirSink)."""
        ...


class LocalDirSink:
    """Results in a local directory, by default results/ in the repository."""

    def __init__(self, root: Path) -> None:
        self.root: Path = root

    def write_text(self, relative_path: str, content: str) -> None:
        """Write one text file at a path relative to the sink root."""
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def location(self, relative_path: str) -> str:
        """Path of a file in the results directory."""
        return str(self.root / relative_path)


# A run id: its UTC start minute (yymmddHHMM) and four random hex characters. The start
# time in every tag lets sweep judge a leftover's age without a timestamp on the object.
RUN_ID = re.compile(r"(\d{10})([0-9a-f]{4})")
TAG_PREFIX = "ptest-"
# Any run tag in a text; legacy run ids were six hex characters. ptest-bootstrap-* is no run tag.
RUN_TAG = re.compile(rf"\b{TAG_PREFIX}(\d{{10}}[0-9a-f]{{4}}|[0-9a-f]{{6}})(?![0-9a-z])")


def new_run_id(now: datetime | None = None) -> str:
    """Return a run id for a run that starts now."""
    started = (now or datetime.now(UTC)).astimezone(UTC)
    return f"{started:%y%m%d%H%M}{secrets.token_hex(2)}"


def run_started(run_id: str) -> datetime | None:
    """Return the start minute a run id carries; None for a legacy id or one whose digits are no date."""
    found = RUN_ID.fullmatch(run_id)
    try:
        return datetime.strptime(found.group(1), "%y%m%d%H%M").replace(tzinfo=UTC) if found else None
    except ValueError:
        return None


def run_tag(run_id: str) -> str:
    """Tag carried by every resource a run creates; sweep finds leftovers by it."""
    return f"{TAG_PREFIX}{run_id}"


def run_dir(started: datetime, env: str, tier: str, run_id: str) -> str:
    """Relative run directory; `_` separates fields because env names contain `-`."""
    utc = started.astimezone(UTC)
    return f"{utc:%Y-%m}/{utc:%Y%m%d-%H%M%S}_{env}_{tier}_{run_id}"


@dataclass
class Counts:
    """Test outcome counts of one run."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    total: int = 0


@dataclass
class Entry:
    """One test with the first line of its message or reason."""

    test_id: str
    message: str
    # The test's sources, "origin: reason" (marker source).
    sources: list[str] = field(default_factory=list[str])
    # The test as a Gherkin scenario (marker scenario); "" without one.
    scenario: str = ""


@dataclass
class Details:
    """The tests of one run that did not simply pass, per outcome."""

    failures: list[Entry] = field(default_factory=list[Entry])
    xfailed: list[Entry] = field(default_factory=list[Entry])
    xpassed: list[Entry] = field(default_factory=list[Entry])
    skipped: list[Entry] = field(default_factory=list[Entry])
    # Pods and nodes that came, went or restarted during the run (workloads.disruptions).
    disruptions: list[str] = field(default_factory=list[str])
    # (test id, Markdown) of each junit property "report", which a test records with record_property.
    reports: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])


@dataclass
class RunInfo:  # pylint: disable=too-many-instance-attributes  # mirrors run.json
    """Contents of run.json."""

    run_id: str
    env: str
    tier: str
    started: str
    finished: str
    exit_code: int
    selection: list[str]
    suite_commit: str
    chart_version: str | None = None
    # What the deployer recorded, e.g. {"monitoring-logging": "checkout ..."}.
    build: dict[str, str] = field(default_factory=dict[str, str])
    capabilities: list[str] = field(default_factory=list[str])
    # Component versions read from the cluster, e.g. {"ita": "3.3.4"}.
    versions: dict[str, str] = field(default_factory=dict[str, str])
    counts: Counts = field(default_factory=Counts)


def suite_commit(repo: Path) -> str:
    """Short git commit of this repository, or 'unknown'."""
    try:
        return (
            run_checked(run_process, ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], 10).strip() or "unknown"
        )
    except ProcessError:
        return "unknown"


def _first_line(text: str | None) -> str:
    return (text or "").partition("\n")[0][:300]


def parse_junit(xml_text: str) -> tuple[Counts, Details]:
    """Return the counts and the tests per outcome from a pytest junit.xml.

    pytest writes a non-strict xpass as a pass; the pytest plugin adds the property "xpass" with its reason.
    """
    counts = Counts()
    details = Details()
    root = ET.fromstring(xml_text)  # nosec B314  # noqa: S314
    for case in root.iter("testcase"):
        _count(case, counts, details)
    return counts, details


def _count(case: ET.Element, counts: Counts, details: Details) -> None:
    """Count one junit testcase and list it under its outcome."""
    counts.total += 1
    test_id = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
    elements = case.iter("property")
    properties = [(prop.get("name"), prop.get("value") or "") for prop in elements]
    found = [value for name, value in properties if name == "source"]
    details.reports += [(test_id, value) for name, value in properties if name == "report"]
    failure = case.find("failure")
    problem = case.find("error") if failure is None else failure
    if problem is not None:
        if problem.tag == "failure":
            counts.failed += 1
        else:
            counts.errors += 1
        story = next((value for name, value in properties if name == "scenario"), "")
        details.failures.append(Entry(test_id, _first_line(problem.get("message")), found, story))
        return
    skipped = case.find("skipped")
    if skipped is not None:
        if skipped.get("type") == "pytest.xfail":
            counts.xfailed += 1
            details.xfailed.append(Entry(test_id, _first_line(skipped.get("message")), found))
        else:
            counts.skipped += 1
            details.skipped.append(Entry(test_id, _first_line(skipped.get("message"))))
        return
    xpass = next((value for name, value in properties if name == "xpass"), None)
    if xpass is None:
        counts.passed += 1
        return
    counts.xpassed += 1
    details.xpassed.append(Entry(test_id, _first_line(xpass), found))


def _by_message(entries: list[Entry]) -> list[str]:
    """One line per distinct message, with its tests, most tests first."""
    groups: dict[str, list[str]] = {}
    for entry in entries:
        groups.setdefault(entry.message or "no reason given", []).append(entry.test_id)
    ordered = sorted(groups.items(), key=lambda item: -len(item[1]))
    lines: list[str] = []
    for message, ids in ordered:
        tests = ", ".join(f"`{test_id}`" for test_id in ids)
        lines.append(f"- {message} ({len(ids)}): {tests}")
    return lines


# Known-defect reasons start with their bug report id, e.g. "[open-zaak-1] ...".
REPORT_ID = re.compile(r"^\[([a-z0-9-]+)\]")
STRICT_XPASS = "[XPASS(strict)] "


def _shown_first(report: tuple[str, list[bool]]) -> tuple[bool, str]:
    """Sort key: reports whose defect did not show in some test first, then by id."""
    return all(report[1]), report[0]


def known_defects(details: Details) -> list[str]:
    """Table rows per bug report: whether its tests still fail; reports whose defect did not show first."""
    shown: dict[str, list[bool]] = {}
    xpassed = [*details.xpassed, *(failure for failure in details.failures if failure.message.startswith(STRICT_XPASS))]
    for entries, failed in ((details.xfailed, True), (xpassed, False)):
        for entry in entries:
            match = REPORT_ID.match(entry.message.removeprefix(STRICT_XPASS))
            shown.setdefault(match.group(1) if match else "no report id", []).append(failed)

    def result(outcomes: list[bool]) -> str:
        if all(outcomes):
            return "still fails"
        if not any(outcomes):
            return "**did not show**"
        return f"**did not show in {outcomes.count(False)} of {len(outcomes)} tests**"

    ordered = sorted(shown.items(), key=_shown_first)
    return [f"| {report} | {result(outcomes)} | {len(outcomes)} |" for report, outcomes in ordered]


# Counts field: column header of the summary table.
_COUNT_COLUMNS = {
    "passed": "Passed",
    "failed": "Failed",
    "errors": "Errors",
    "skipped": "Skipped",
    "xfailed": "XFailed",
    "xpassed": "XPassed",
    "total": "Total",
}


def summary_markdown(info: RunInfo, details: Details) -> str:
    """Human-readable summary.md of one run; results/README.md explains the outcomes."""
    build = "; ".join(f"{name} {version}" for name, version in sorted(info.build.items()))
    pairs = sorted(info.versions.items())
    versions = ", ".join(f"{name} {version}" for name, version in pairs) or "unknown"
    lines = [
        f"# {info.env} {info.tier} {info.run_id}",
        "",
        f"- Started: {info.started}",
        f"- Finished: {info.finished}",
        f"- Exit code: {info.exit_code}",
        f"- Chart version: {info.chart_version or 'unknown'}",
        *([f"- Deployed build: {build}"] if info.build else []),
        f"- Component versions: {versions}",
        f"- Suite commit: {info.suite_commit}",
        "- What the outcomes mean: [results/README.md](../../README.md)",
        "",
        f"| {' | '.join(_COUNT_COLUMNS.values())} |",
        f"|{'---|' * len(_COUNT_COLUMNS)}",
        f"| {' | '.join(str(getattr(info.counts, count)) for count in _COUNT_COLUMNS)} |",
    ]
    return "\n".join([*lines, *_detail_lines(details), ""])


def _detail_lines(details: Details) -> list[str]:
    """Return the sections of summary.md after the counts; only those with content."""
    lines: list[str] = []
    rows = known_defects(details)
    if rows:
        lines += ["", "## Known defects", "", "| Report | Result | Tests |", "|---|---|---|", *rows]
    if details.disruptions:
        lines += ["", "## Pods replaced or restarted during the run", ""]
        lines += [f"- {disruption}" for disruption in details.disruptions]
    reports = (["", f"## Report of `{test_id}`", "", report] for test_id, report in details.reports)
    lines += chain.from_iterable(reports)
    if details.failures:
        lines += ["", "## Failed and errors", ""]
        lines += [f"- `{failure.test_id}`: {failure.message or 'no message'}" for failure in details.failures]
    sections = [
        ("Known defects that did not show (XPassed)", details.xpassed),
        ("Known defects (XFailed)", details.xfailed),
        ("Skipped", details.skipped),
    ]
    for title, entries in sections:
        if entries:
            lines += ["", f"## {title}", "", *_by_message(entries)]
    sourced = [entry for entry in (*details.xpassed, *details.xfailed, *details.failures) if entry.sources]
    if sourced:
        lines += ["", "## Sources of the failed and known-defect tests", ""]
        lines += [f"- `{entry.test_id}`: {'; '.join(entry.sources)}" for entry in sourced]
    return lines + _scenario_lines(details)


def _scenario_lines(details: Details) -> list[str]:
    told = [failure for failure in details.failures if failure.scenario]
    if not told:
        return []
    lines = ["", "## Scenarios of the failed tests", ""]
    for entry in told:
        lines.extend((f"`{entry.test_id}`", "", "```gherkin", entry.scenario, "```", ""))
    return lines[:-1]


def write_run(sink: ResultsSink, directory: str, info: RunInfo, details: Details, redactor: Redactor) -> None:
    """Write run.json and summary.md; every text passes the redactor first."""
    sink.write_text(f"{directory}/run.json", redactor.redact(f"{json.dumps(asdict(info), indent=2)}\n"))
    sink.write_text(f"{directory}/summary.md", redactor.redact(summary_markdown(info, details)))


def now_iso(timespec: str = "seconds") -> str:
    """Return the current UTC time, ISO 8601, to the given precision (datetime.isoformat timespec)."""
    return datetime.now(UTC).isoformat(timespec=timespec)
