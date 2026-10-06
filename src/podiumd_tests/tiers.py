"""Tier presets: what `podiumd-tests run --tier X` selects (PLAN.md §3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    """Test paths and marker expression of one tier."""

    paths: tuple[str, ...]
    marker_expression: str
    description: str


TIERS: dict[str, Tier] = {
    "smoke": Tier(("tests/smoke",), "not destructive", "read-only: is it up and wired"),
    "core": Tier(
        ("tests/smoke", "tests/component", "tests/integration"),
        "(smoke or core) and not destructive",
        "smoke plus the key user flows",
    ),
    "full": Tier(
        ("tests/smoke", "tests/component", "tests/integration"),
        "not destructive",
        "smoke, component and integration",
    ),
    "perf": Tier(("tests/perf",), "perf", "response-time thresholds (Locust)"),
    "chaos": Tier(
        ("tests/smoke", "tests/component", "tests/integration"),
        "destructive",
        "destructive and chaos tests; opt-in",
    ),
}
