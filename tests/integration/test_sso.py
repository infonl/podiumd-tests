"""Chain: one Keycloak login opens the admin of every Django app that logs in through Keycloak.

Ported from TA smoke 92. The test admin logs in at the first such app; each other app's
/oidc/authenticate/ must then come back from Keycloak without a login form. An app whose admin
does not log in through Keycloak (its /oidc/authenticate/ does not redirect there) is skipped.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak import realm_url
from podiumd_tests.auth.keycloak_admin import realm_of
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.browser import keycloak_login
from podiumd_tests.components import DJANGO_APPS
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.integration, pytest.mark.ui, pytest.mark.requires("keycloak")]

AUTHENTICATE = "/oidc/authenticate/?next=/admin/"
# The logout control of the Django admins, in Dutch or English.
LOGOUT = re.compile("Afmelden|Uitloggen|Log out", re.IGNORECASE)


def logs_in_through_keycloak(http: requests.Session, url: str, keycloak: str) -> bool:
    """Whether the app's admin login redirects to Keycloak."""
    response = http.get(url + AUTHENTICATE, allow_redirects=False)
    return response.is_redirect and url_host(response.headers["Location"]) == url_host(keycloak)


@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
@pytest.mark.tc("FB-005")
def test_one_login_opens_every_admin(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    component: str,
) -> None:
    """After a Keycloak login at another app's admin, this app's admin needs no new login (TA smoke 92)."""
    keycloak = urls["keycloak"]
    sso = [c for c in DJANGO_APPS if c in urls and logs_in_through_keycloak(http, urls[c], keycloak)]
    if component not in sso:
        pytest.skip(f"{component}'s admin does not log in through Keycloak")
    others = [c for c in sso if c != component]
    if not others:
        pytest.skip("no other app's admin logs in through Keycloak")
    need_bootstrap(ADMIN.name)
    page.goto(urls[others[0]] + AUTHENTICATE)
    keycloak_login(page, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
    page.wait_for_url(lambda url: url_host(url) == url_host(urls[others[0]]))
    page.goto(urls[component] + AUTHENTICATE)
    page.wait_for_url(lambda url: url_host(url) == url_host(urls[component]))
    assert not page.url.startswith(realm_url(keycloak, realm_of(podiumd_env))), "Keycloak asked for a new login"
    # A failing OIDC callback also ends on the app's host, on an error page.
    assert "/admin" in page.url, f"the login did not reach {component}'s admin: {page.url}"


@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
@pytest.mark.tc("FB-006")
def test_admin_logout_returns_to_the_login(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    component: str,
) -> None:
    """Logging out of the app's admin ends the session: the admin then asks for a login again."""
    if not logs_in_through_keycloak(http, urls[component], urls["keycloak"]):
        pytest.skip(f"{component}'s admin does not log in through Keycloak")
    need_bootstrap(ADMIN.name)
    page.goto(urls[component] + AUTHENTICATE)
    keycloak_login(page, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
    page.wait_for_url(lambda url: url_host(url) == url_host(urls[component]) and "/admin" in url)
    page.get_by_role("button", name=LOGOUT).or_(page.get_by_role("link", name=LOGOUT)).first.click()
    page.goto(urls[component] + "/admin/")
    assert "login" in page.url or url_host(page.url) == url_host(urls["keycloak"]), f"still in the admin: {page.url}"
