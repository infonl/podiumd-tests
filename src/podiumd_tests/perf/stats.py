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


def thresholds(path: Path, endpoint: str) -> Threshold:
    """The endpoint's threshold: perf.yaml's defaults with its entry under `endpoints` on top."""
    data = cast("dict[str, object]", yaml.safe_load(path.read_text(encoding="utf-8")))
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
            found[row["Name"]] = EndpointStats(int(row["Request Count"]), int(row["Failure Count"]), float(row["95%"]))
    return found


def violations(stats: EndpointStats, threshold: Threshold) -> list[str]:
    """What the stats exceed of the threshold; empty when they meet it."""
    found: list[str] = []
    if stats.requests == 0:
        return ["no requests"]
    if stats.p95_ms > threshold.p95_ms:
        found.append(f"p95 {stats.p95_ms:.0f} ms > {threshold.p95_ms:.0f} ms")
    if stats.failures / stats.requests > threshold.max_failure_ratio:
        found.append(f"{stats.failures}/{stats.requests} failed > {threshold.max_failure_ratio:.0%}")
    return found


STATS = "locust_stats.csv"
SETTINGS = "settings.json"
BASELINE_RUNS = 5
# Fewer earlier runs give no baseline: one 30 s run's p95 swings with a single slow request.
MIN_BASELINE_RUNS = 3


def earlier_stats(run: Path) -> list[dict[str, EndpointStats]]:
    """The stats of earlier perf runs of the same environment with the same settings.json, newest first.

    run is this run's directory, <results>/<yyyy-mm>/<start>_<env>_perf_<run id>; its perf/ holds both files.
    """
    env = run.name.split("_")[1]
    settings = (run / "perf" / SETTINGS).read_text(encoding="utf-8")
    found: list[dict[str, EndpointStats]] = []
    for other in sorted(run.parent.parent.glob(f"*/*_{env}_perf_*"), reverse=True):
        perf = other / "perf"
        if other.name >= run.name or not (perf / STATS).is_file() or not (perf / SETTINGS).is_file():
            continue
        if (perf / SETTINGS).read_text(encoding="utf-8") == settings:
            found.append(read_stats((perf / STATS).read_text(encoding="utf-8")))
    return found


def baseline_p95(history: list[dict[str, EndpointStats]], endpoint: str) -> float | None:
    """Median p95 of the endpoint over the newest BASELINE_RUNS runs with it; None below MIN_BASELINE_RUNS runs."""
    values = [h[endpoint].p95_ms for h in history if endpoint in h and h[endpoint].requests][:BASELINE_RUNS]
    return statistics.median(values) if len(values) >= MIN_BASELINE_RUNS else None


def slowdown_limit(threshold: Threshold, baseline_ms: float) -> float:
    """The highest p95 that is no slowdown: above both max_slowdown times and min_slowdown_ms more than the baseline.

    The margin keeps noise on small numbers (a p95 of 130 ms becoming 260 ms) from counting as a slowdown.
    """
    return max(threshold.max_slowdown * baseline_ms, baseline_ms + threshold.min_slowdown_ms)
