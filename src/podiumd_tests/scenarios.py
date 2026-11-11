"""Marker scenario(text): the test as a Gherkin scenario (Given, When, Then) for the people who read the report."""

from __future__ import annotations

import textwrap

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

KEYWORDS = ("Given", "When", "Then", "And", "But")


def scenario(item: pytest.Item) -> str:
    """Return the test's scenario from its nearest marker, dedented; "" without one."""
    marker = item.get_closest_marker("scenario")
    if marker is None or not marker.args:
        return ""
    return textwrap.dedent(str(marker.args[0])).strip()


def scenario_problems(item: pytest.Item) -> list[str]:
    """Why the test's scenario is malformed; empty when it is fine or the test has none."""
    lines = [line.strip() for line in scenario(item).splitlines() if line.strip()]
    if not lines:
        return []
    problems = [
        f"{item.nodeid}: scenario line starts with none of {', '.join(KEYWORDS)}: {line!r}"
        for line in lines
        if line.split()[0] not in KEYWORDS
    ]
    words = [line.split()[0] for line in lines]
    if words[0] != "Given" and words[0] != "When":
        problems.append(f"{item.nodeid}: scenario starts with {words[0]!r}, not Given or When")
    if "Then" not in words:
        problems.append(f"{item.nodeid}: scenario has no Then")
    return problems
