"""WCAG 2.1 AA scans with axe-core, injected into the page the browser shows."""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import entries

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from podiumd_tests.json_data import JsonObject

WCAG_21_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]


@cache
def _axe_script() -> str:
    # axe-playwright-python is used only for the axe-core build it ships.
    return files("axe_playwright_python").joinpath("axe.min.js").read_text(encoding="utf-8")


def wcag_violations(page: Page) -> list[JsonObject]:
    """The WCAG 2.1 AA rules the page violates, as axe-core reports them."""
    page.evaluate(_axe_script())
    options = {"runOnly": {"type": "tag", "values": WCAG_21_AA}, "resultTypes": ["violations"]}
    result = cast("JsonObject", page.evaluate("options => axe.run(document, options)", options))
    return entries(result.get("violations"))


def describe_violation(violation: JsonObject) -> str:
    """One line per violation: rule, impact, number of elements and axe-core's help text."""
    nodes = len(entries(violation.get("nodes")))
    return f"{violation.get('id')} ({violation.get('impact')}, {nodes} elements): {violation.get('help')}"
