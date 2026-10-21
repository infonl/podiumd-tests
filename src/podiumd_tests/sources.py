"""Marker source(origin, reason): where a test comes from and why it exists, in the words of that source."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# First word of an origin: the source repository (MIGRATION.md), draaiboek for a draaiboek case, or this suite.
ORIGINS = {
    "TA": "icatt-menselijk-digitaal/podiumd-testautomation",
    "MK": "infonl/podiumd-minikube/tests",
    "PI": "icatt-menselijk-digitaal/podiumd-infra/tests",
    "EX": "scctwente/ExternalsPodiumD/smoke-tests",
    "ZAC": "infonl/dimpact-zaakafhandelcomponent/src/e2e",
    "draaiboek": "TA test-catalog/cases.yaml",
    "podiumd-tests": "made in this suite",
}


def sources(item: pytest.Item) -> list[str]:
    """The test's sources as "origin: reason", nearest marker first."""
    return [f"{m.args[0]}: {m.args[1]}" for m in item.iter_markers("source")]


def source_problems(item: pytest.Item) -> list[str]:
    """Why the test's source markers are missing or malformed; empty when they are fine."""
    markers = list(item.iter_markers("source"))
    if not markers:
        return [f"{item.nodeid}: no @pytest.mark.source(origin, reason)"]
    problems: list[str] = []
    for marker in markers:
        args = marker.args
        if len(args) != 2 or not all(isinstance(a, str) and a.strip() for a in args):  # pyright: ignore[reportUnknownVariableType]
            problems.append(f"{item.nodeid}: source needs two texts, origin and reason: {args!r}")
        elif str(args[0]).split()[0] not in ORIGINS:
            problems.append(f"{item.nodeid}: source origin {args[0]!r} starts with none of {', '.join(ORIGINS)}")
    return problems
