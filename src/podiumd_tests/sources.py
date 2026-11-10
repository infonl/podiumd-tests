"""Marker source(origin, reason): where a test comes from and why it exists, in the words of that source."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# @pytest.mark.source(origin, reason)
SOURCE_ARGS = 2

# First word of an origin: the source repository (MIGRATION.md), a component's own one, a draaiboek case, or this suite.
ORIGINS = {
    "TA": "icatt-menselijk-digitaal/podiumd-testautomation",
    "MK": "infonl/podiumd-minikube/tests",
    "PI": "icatt-menselijk-digitaal/podiumd-infra/tests",
    "EX": "scctwente/ExternalsPodiumD/smoke-tests",
    "ZAC": "infonl/dimpact-zaakafhandelcomponent/src/e2e",
    # Another component's own repository, named after the word: "upstream <owner>/<repo> <path>".
    "upstream": "a component's own repository (docs/research/upstream-tests.md)",
    "draaiboek": "TA test-catalog/cases.yaml",
    "podiumd-tests": "made in this suite",
}


def sources(item: pytest.Item) -> list[str]:
    """The test's sources as "origin: reason", nearest marker first."""
    return [f"{marker.args[0]}: {marker.args[1]}" for marker in item.iter_markers("source")]


def source_problems(item: pytest.Item) -> list[str]:
    """Why the test's source markers are missing or malformed; empty when they are fine."""
    markers = list(item.iter_markers("source"))
    if not markers:
        return [f"{item.nodeid}: no @pytest.mark.source(origin, reason)"]
    problems: list[str] = []
    for marker in markers:
        args = marker.args
        texts = all(isinstance(arg, str) and arg.strip() for arg in args)
        if len(args) != SOURCE_ARGS or not texts:
            problems.append(f"{item.nodeid}: source needs two texts, origin and reason: {args!r}")
        elif str(args[0]).split()[0] not in ORIGINS:
            problems.append(f"{item.nodeid}: source origin {args[0]!r} starts with none of {', '.join(ORIGINS)}")
    return problems
