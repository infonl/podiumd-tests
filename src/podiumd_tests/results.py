"""Run results under results/<YYYY-MM>/<timestamp>_<env>_<tier>_<runid>/ (PLAN.md §7).

All writing goes through a ResultsSink, so results can move to another
repository or a static site later without touching the callers.
"""

from __future__ import annotations

import json
import secrets

# Parses only the junit.xml written by our own pytest run.
import xml.etree.ElementTree as ET  # nosec B405

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Protocol

from podiumd_tests.process import ProcessError
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process

if TYPE_CHECKING:
    from pathlib import Path

    from podiumd_tests.credentials import Redactor


class ResultsSink(Protocol):
    """Where run results are written; LocalDirSink for now, other sinks later."""

    def write_text(self, relative_path: str, content: str) -> None:
        """Write one text file at a path relative to the sink root."""
        ...

    def location(self, relative_path: str) -> str:
        """Human-readable location of a relative path (a file path for LocalDirSink)."""
        ...


class LocalDirSink:
    """Results in a local directory, by default results/ in the repository."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write_text(self, relative_path: str, content: str) -> None:
        """Write one text file at a path relative to the sink root."""
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def location(self, relative_path: str) -> str:
        """Path of a file in the results directory."""
        return str(self.root / relative_path)


def new_run_id() -> str:
    """Six hex characters that make a run directory unique."""
    return secrets.token_hex(3)


def run_tag(run_id: str) -> str:
    """Tag carried by every resource a run creates (PLAN.md R9); sweep finds leftovers by it."""
    return f"ptest-{run_id}"


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
    total: int = 0


@dataclass
class Failure:
    """One failed or errored test with the first line of its message."""

    test_id: str
    message: str


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
    capabilities: list[str] = field(default_factory=list[str])
    counts: Counts = field(default_factory=Counts)


def suite_commit(repo: Path) -> str:
    """Short git commit of this repository, or 'unknown'."""
    try:
        return (
            run_checked(run_process, ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], 10).strip() or "unknown"
        )
    except ProcessError:
        return "unknown"


def parse_junit(xml_text: str) -> tuple[Counts, list[Failure]]:
    """Counts and failures from a pytest junit.xml."""
    counts = Counts()
    failures: list[Failure] = []
    root = ET.fromstring(xml_text)  # nosec B314  # noqa: S314
    for case in root.iter("testcase"):
        counts.total += 1
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None:
            counts.failed += 1
            failures.append(Failure(test_id, (failure.get("message") or "").splitlines()[0][:200]))
        elif error is not None:
            counts.errors += 1
            failures.append(Failure(test_id, (error.get("message") or "").splitlines()[0][:200]))
        elif skipped is not None:
            if skipped.get("type") == "pytest.xfail":
                counts.xfailed += 1
            else:
                counts.skipped += 1
        else:
            counts.passed += 1
    return counts, failures


def summary_markdown(info: RunInfo, failures: list[Failure]) -> str:
    """Human-readable summary.md of one run."""
    c = info.counts
    lines = [
        f"# {info.env} {info.tier} {info.run_id}",
        "",
        f"- Started: {info.started}",
        f"- Finished: {info.finished}",
        f"- Exit code: {info.exit_code}",
        f"- Chart version: {info.chart_version or 'unknown'}",
        f"- Suite commit: {info.suite_commit}",
        "",
        "| Passed | Failed | Errors | Skipped | Xfailed | Total |",
        "|---|---|---|---|---|---|",
        f"| {c.passed} | {c.failed} | {c.errors} | {c.skipped} | {c.xfailed} | {c.total} |",
    ]
    if failures:
        lines += ["", "## Failures", ""]
        lines += [f"- `{f.test_id}`: {f.message or 'no message'}" for f in failures]
    return "\n".join(lines) + "\n"


def write_run(sink: ResultsSink, directory: str, info: RunInfo, failures: list[Failure], redactor: Redactor) -> None:
    """Write run.json and summary.md; every text passes the redactor first."""
    sink.write_text(f"{directory}/run.json", redactor.redact(json.dumps(asdict(info), indent=2) + "\n"))
    sink.write_text(f"{directory}/summary.md", redactor.redact(summary_markdown(info, failures)))


def now_iso() -> str:
    """Current UTC time, ISO 8601, seconds precision."""
    return datetime.now(UTC).isoformat(timespec="seconds")
