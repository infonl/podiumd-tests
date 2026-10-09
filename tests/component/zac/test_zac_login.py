"""ZAC in a browser: the OIDC login through Keycloak ends on a rendered dashboard. Ported from MK test_browser.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.browser import redirect_login

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.core, pytest.mark.requires("zac", "keycloak")]


@pytest.mark.tc("ZAC-002")
def test_login_shows_the_dashboard(
    page: Page, podiumd_env: Environment, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """The test admin logs in through Keycloak and ZAC renders its dashboard (a blank SPA also answers 200)."""
    need_bootstrap(ADMIN.name)
    redirect_login(page, podiumd_env, urls["zac"], ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
    # The navigation only renders once the SPA has loaded the user's rights.
    expect(page.get_by_role("button", name="Dashboard", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Menu voor zaken", exact=True)).to_be_visible()
