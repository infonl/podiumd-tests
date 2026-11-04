"""Open Inwoner's pages raise no Content-Security-Policy or Permissions-Policy violation in the browser."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.browser import keycloak_login
from podiumd_tests.browser import refuse_cookies
from podiumd_tests.oidc import LOGIN_PATHS

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("openinwoner")]

PUBLIC_PAGES = ("/", "/search/?term=informatie", "/contactformulier/")
# The admin's own pages and a rich text editor, where a stricter staff CSP shows first.
ADMIN_PAGES = ("/admin/", "/admin/pdc/product/add/", "/admin/accounts/user/")
# Chromium's console texts for a blocked resource or feature. Not "Error with Permissions-Policy
# header: Unrecognized feature", which Chromium logs for a feature it does not know and blocks nothing.
POLICY_TEXTS = ("violates the following Content Security Policy", "Permissions policy violation")


def watch_violations(page: Page) -> list[str]:
    """The policy violations the browser reports on the page from now on; the list fills as they come."""
    found: list[str] = []
    page.on(
        "console", lambda message: found.extend([message.text] if any(t in message.text for t in POLICY_TEXTS) else [])
    )
    return found


def visit(page: Page, base: str, paths: tuple[str, ...]) -> list[str]:
    """Open each page until its network is idle; the violations, each with the page it showed on."""
    found = watch_violations(page)
    reported: list[str] = []
    for path in paths:
        page.goto(base + path, wait_until="networkidle")
        reported += [f"{path}: {text}" for text in found]
        found.clear()
    return reported


@pytest.mark.source(
    "podiumd-tests",
    "Open Inwoner 2.5.0 enforces a stricter CSP for staff and a Permissions Policy; a page it breaks shows it in the console.",
)
def test_public_pages_raise_no_policy_violation(page: Page, podiumd_env: Environment) -> None:
    """The homepage, search and contact form raise no CSP or Permissions-Policy violation."""
    base = podiumd_env.profile.urls["openinwoner"]
    page.goto(base + "/")
    refuse_cookies(page)
    assert not visit(page, base, PUBLIC_PAGES)


@pytest.mark.source(
    "podiumd-tests",
    "Open Inwoner 2.5.0 enforces a stricter CSP for staff and a Permissions Policy; a page it breaks shows it in the console.",
)
def test_admin_pages_raise_no_policy_violation(
    page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> None:
    """The admin, logged in as staff through Keycloak, raises no CSP or Permissions-Policy violation."""
    need_bootstrap(ADMIN.name)
    base = podiumd_env.profile.urls["openinwoner"]
    page.goto(base + LOGIN_PATHS["openinwoner"])
    keycloak_login(page, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
    assert not visit(page, base, ADMIN_PAGES)
    assert page.url == base + ADMIN_PAGES[-1], f"not logged in to the admin: {page.url}"
