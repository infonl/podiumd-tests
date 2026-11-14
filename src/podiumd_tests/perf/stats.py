"""Locust's stats CSV and the p95 and failure-ratio thresholds of perf.yaml."""

from __future__ import annotations

import csv
import io
import statistics

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

import yaml

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Mapping
    from pathlib import Path


@dataclass(frozen=True)
class Threshold:
    """The most an endpoint may take: p95 response time, share of failed requests and slowdown against earlier runs."""

    p95_ms: float
    max_failure_ratio: float
    max_slowdown: float
    min_slowdown_ms: float


@dataclass(frozen=True)
class EndpointStats:
    """One endpoint's row in Locust's stats CSV."""

    requests: int
    failures: int
    p95_ms: float
    per_second: float = 0


def perf_settings(path: Path) -> dict[str, object]:
    """Return perf.yaml's contents."""
    return cast("dict[str, object]", yaml.safe_load(path.read_text(encoding="utf-8")))


def thresholds(path: Path, endpoint: str) -> Threshold:
    """Return the endpoint's threshold: perf.yaml's defaults with its entry under `endpoints` on top."""
    data = perf_settings(path)
    endpoints = cast("dict[str, dict[str, float]]", data.get("endpoints") or {})
    merged = {**cast("dict[str, float]", data["defaults"]), **endpoints.get(endpoint, {})}
    return Threshold(
        float(merged["p95_ms"]),
        float(merged["max_failure_ratio"]),
        float(merged["max_slowdown"]),
        float(merged["min_slowdown_ms"]),
    )


def read_stats(csv_text: str) -> dict[str, EndpointStats]:
    """Stats per endpoint name from Locust's <prefix>_stats.csv, without the Aggregated row."""
    found: dict[str, EndpointStats] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row["Name"] != "Aggregated":
            requests, failures = int(row["Request Count"]), int(row["Failure Count"])
            per_second = float(row.get("Requests/s") or 0)
            found[row["Name"]] = EndpointStats(requests, failures, float(row["95%"]), per_second)
    return found


def read_failures(csv_text: str) -> list[tuple[str, str, int]]:
    """(name, error, occurrences) per row of Locust's <prefix>_failures.csv, most frequent first."""
    rows = [_failure(row) for row in csv.DictReader(io.StringIO(csv_text))]
    return sorted(rows, key=lambda row: -row[2])


def _failure(row: dict[str, str]) -> tuple[str, str, int]:
    return row["Name"], row["Error"], int(row["Occurrences"])


# Separates an endpoint's name from a number its requests are split by: users of a ramp step, links of a hot zaak.
LABEL = "@"


def labelled(endpoint: str, number: int) -> str:
    """Return the stats name of the endpoint's requests at a number."""
    return f"{endpoint}{LABEL}{number}"


def by_label(stats: Mapping[str, EndpointStats]) -> dict[int, dict[str, EndpointStats]]:
    """Return the stats of labelled names per number (ascending) and endpoint; other names are left out."""
    found: dict[int, dict[str, EndpointStats]] = {}
    for name, endpoint_stats in stats.items():
        endpoint, separator, number = name.rpartition(LABEL)
        if separator and number.isdigit():
            found.setdefault(int(number), {})[endpoint] = endpoint_stats
    return dict(sorted(found.items()))


def summed(parts: Iterable[EndpointStats]) -> EndpointStats:
    """Return the parts' requests and failures added up, with the highest p95 of them."""
    listed = list(parts)
    return EndpointStats(
        sum(part.requests for part in listed),
        sum(part.failures for part in listed),
        max((part.p95_ms for part in listed), default=0),
        sum(part.per_second for part in listed),
    )


def violations(stats: EndpointStats, threshold: Threshold) -> list[str]:
    """Return what the stats exceed of the threshold; empty when they meet it."""
    found: list[str] = []
    if stats.requests == 0:
        return ["no requests"]
    if stats.p95_ms > threshold.p95_ms:
        found.append(f"p95 {stats.p95_ms:.0f} ms > {threshold.p95_ms:.0f} ms")
    if stats.failures / stats.requests > threshold.max_failure_ratio:
        found.append(f"{stats.failures}/{stats.requests} failed > {threshold.max_failure_ratio:.0%}")
    return found


STATS = "locust_stats.csv"
# Written with --csv-full-history: a row per endpoint and second.
HISTORY = "locust_stats_history.csv"
FAILURES = "locust_failures.csv"


def locust_csv(prefix: Path, name: str) -> Path:
    """Return the path of Locust's CSV of this name (STATS, HISTORY, FAILURES) for a run with --csv prefix."""
    return prefix.with_name(prefix.name + name.removeprefix("locust"))


SETTINGS = "settings.json"
BASELINE_RUNS = 5
# Fewer earlier runs give no baseline: one 30 s run's p95 swings with a single slow request.
MIN_BASELINE_RUNS = 3


def earlier_stats(run: Path) -> list[dict[str, EndpointStats]]:
    """Return the stats of earlier perf runs of the same environment with the same settings.json, newest first.

    run is this run's directory, <results>/<yyyy-mm>/<start>_<env>_perf_<run id>; its perf/ holds both files.
    """
    env = run.name.split("_")[1]
    settings = (run / "perf" / SETTINGS).read_text(encoding="utf-8")
    found: list[dict[str, EndpointStats]] = []
    for other in sorted(run.parent.parent.glob(f"*/*_{env}_perf_*"), reverse=True):
        perf = other / "perf"
        complete = (perf / STATS).is_file() and (perf / SETTINGS).is_file()
        if other.name >= run.name or not complete:
            continue
        if (perf / SETTINGS).read_text(encoding="utf-8") == settings:
            found.append(read_stats((perf / STATS).read_text(encoding="utf-8")))
    return found


def baseline_p95(history: list[dict[str, EndpointStats]], endpoint: str) -> float | None:
    """Median p95 of the endpoint over the newest BASELINE_RUNS runs with it; None below MIN_BASELINE_RUNS runs."""
    measured = [run[endpoint] for run in history if endpoint in run and run[endpoint].requests]
    values = [endpoint_stats.p95_ms for endpoint_stats in measured[:BASELINE_RUNS]]
    return statistics.median(values) if len(values) >= MIN_BASELINE_RUNS else None


def slowdown_limit(threshold: Threshold, baseline_ms: float) -> float:
    """Return the highest p95 that is no slowdown: above both max_slowdown times and min_slowdown_ms over the baseline.

    The margin keeps noise on small numbers (a p95 of 130 ms becoming 260 ms) from counting as a slowdown.
    """
    return max(threshold.max_slowdown * baseline_ms, baseline_ms + threshold.min_slowdown_ms)
