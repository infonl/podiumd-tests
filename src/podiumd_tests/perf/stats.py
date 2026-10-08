"""Locust's stats CSV and the p95 and failure-ratio thresholds of perf.yaml."""

from __future__ import annotations

import csv
import io

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

import yaml

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class Threshold:
    """The most an endpoint may take: p95 response time and share of failed requests."""

    p95_ms: float
    max_failure_ratio: float


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
    return Threshold(float(merged["p95_ms"]), float(merged["max_failure_ratio"]))


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
