"""ZAC in a browser: the OIDC login through Keycloak ends on a rendered dashboard. Ported from MK test_browser.py."""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.steps import KeycloakUser
from podiumd_tests.browser import keycloak_login

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.core, pytest.mark.requires("zac", "keycloak")]

ADMIN = KeycloakUser("admin")


def test_login_shows_the_dashboard(
    page: Page, podiumd_env: Environment, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """The test admin logs in through Keycloak and ZAC renders its dashboard (a blank SPA also answers 200)."""
    need_bootstrap(ADMIN.name)
    page.goto(urls["zac"] + "/")
    keycloak_login(page, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
    expect(page).to_have_url(re.compile(re.escape(urls["zac"])))
    # The navigation only renders once the SPA has loaded the user's rights.
    expect(page.get_by_role("button", name="Dashboard")).to_be_visible()
    expect(page.get_by_role("button", name="Menu voor zaken")).to_be_visible()
