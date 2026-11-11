"""ZaakBrug's Frank!Framework console: its login through Keycloak (client zaakbrug) and the role it needs."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.browser import browser_session
from podiumd_tests.browser import keycloak_login
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("zaakbrug", "keycloak")]

CONSOLE = "/iaf/gui/"
SERVER_INFO = "/iaf/api/server/info"


def console_login(page: Page, env: Environment, user: KeycloakUser) -> requests.Session:
    """Open ZaakBrug's console, log in on Keycloak's form, and return the browser's session on ZaakBrug."""
    zaakbrug = env.profile.urls["zaakbrug"]
    page.goto(zaakbrug + CONSOLE)
    keycloak_login(page, user.username, env.credentials.get(user.store_key))
    page.wait_for_url(lambda url: url_host(url) == url_host(zaakbrug) and CONSOLE in url)
    return browser_session(page, env)


@pytest.mark.source(
    "podiumd-tests",
    "podiumd-infra rotates the console's Keycloak client secret; only a real login proves the code exchange.",
)
@pytest.mark.scenario("""
    Given a user with ZaakBrug's console role zaakbrug_admin
    When the user opens ZaakBrug's console and logs in through Keycloak
    Then the console opens
    And Frank!Framework's API answers with ZaakBrug's server information
""")
def test_console_login_through_keycloak(
    page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> None:
    """The console's OIDC login ends in a session that Frank!Framework's API accepts."""
    need_bootstrap(ADMIN.name)
    http = console_login(page, podiumd_env, ADMIN)
    info = expect_status(http.get(podiumd_env.profile.urls["zaakbrug"] + SERVER_INFO), HTTPStatus.OK).json()
    assert info["instance"]["version"], info


@pytest.mark.source(
    "podiumd-tests", "The console maps Keycloak client roles of zaakbrug to Frank!Framework roles; others get nothing."
)
@pytest.mark.scenario("""
    Given a user without a role of ZaakBrug's Keycloak client
    When the user logs in to ZaakBrug's console through Keycloak
    Then Frank!Framework's API refuses the user with Access Denied
""")
def test_console_refuses_a_user_without_a_zaakbrug_role(
    page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> None:
    """A Keycloak user without a zaakbrug client role logs in but gets no data (Frank answers 500 Access Denied)."""
    need_bootstrap(KCC.name)
    http = console_login(page, podiumd_env, KCC)
    refused = http.get(podiumd_env.profile.urls["zaakbrug"] + SERVER_INFO)
    assert refused.status_code != HTTPStatus.OK, refused.text[:200]
    assert "Access Denied" in refused.text, refused.text[:200]
