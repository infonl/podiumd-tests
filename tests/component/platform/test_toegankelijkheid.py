"""WCAG 2.1 AA: the public pages have no critical axe-core violations.

Ported from TA regression 172. As in TA, only critical violations fail; serious ones need a vendor
fix (minikube: color-contrast and link-name on the portal homepage). TA's check that a form does not require every field is dropped: the
test form has one field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.accessibility import describe_violation
from podiumd_tests.accessibility import wcag_violations
from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.browser import refuse_cookies
from podiumd_tests.pytest_plugin import requiring

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

pytestmark = [pytest.mark.component, pytest.mark.ui]


@pytest.mark.parametrize(
    ("component", "path"),
    [requiring("openinwoner", "openinwoner", "/"), requiring("openformulieren", "openformulieren", f"/{TEST_FORM}/")],
)
def test_page_has_no_critical_wcag_violation(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    urls: dict[str, str],
    need_bootstrap: Callable[..., None],
    component: str,
    path: str,
) -> None:
    """The portal homepage and the test form, as rendered, have no critical WCAG 2.1 AA violation (TA reg-172)."""
    if component == "openformulieren":
        need_bootstrap("openformulieren-form")
    page.goto(urls[component] + path)
    if component == "openinwoner":
        refuse_cookies(page)
    else:
        # The form SDK renders the start page, with its heading, after the page has loaded.
        expect(page.get_by_role("heading", name=TEST_FORM)).to_be_visible()
    critical = [describe_violation(v) for v in wcag_violations(page) if v.get("impact") == "critical"]
    assert critical == []
