"""Chain: one Keycloak login opens the admin of every Django app that logs in through Keycloak.

Ported from TA smoke 92. The test admin logs in at the first such app; each other app's
/oidc/authenticate/ must then come back from Keycloak without a login form. An app whose admin
does not log in through Keycloak (its /oidc/authenticate/ does not redirect there) is skipped.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

from podiumd_tests.auth.keycloak import realm_url
from podiumd_tests.auth.keycloak_admin import realm_of
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.browser import keycloak_login
from podiumd_tests.components import DJANGO_APPS
from podiumd_tests.oidc import LOGIN_PATHS
from podiumd_tests.oidc import keycloak_hosts
from podiumd_tests.oidc import logs_in_through_keycloak
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import url_host
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.integration, pytest.mark.ui, pytest.mark.requires("keycloak")]

BUSY_APP_TIMEOUT = 240
# The logout control of the Django admins, in Dutch or English.
LOGOUT = re.compile("Afmelden|Uitloggen|Log out", re.IGNORECASE)


def in_admin(url: str, app_url: str) -> bool:
    """Whether the URL is a page of the logged-in admin: not its login (or login failure) page, nor OIDC's own pages."""
    path = urlsplit(url).path
    return url_host(url) == url_host(app_url) and path.startswith("/admin") and not path.startswith("/admin/login")


@pytest.fixture(scope="module", name="sso_admins")
def fixture_sso_admins(http: requests.Session, urls: dict[str, str], podiumd_env: Environment) -> dict[str, str]:
    """Admin URL per Django app whose admin logs in through Keycloak; asked once, not by every test at once.

    An app busy with the other workers' browser logins may time out (Open Formulieren on kees00: 504
    after 60 s); it is asked again.
    """
    hosts = keycloak_hosts(urls)

    def through_keycloak(component: str, url: str) -> bool:
        def probe() -> tuple[bool]:  # a tuple: False is an answer, not "not yet"
            return (logs_in_through_keycloak(http, url + LOGIN_PATHS[component], hosts),)

        return wait_until(probe, timeout=BUSY_APP_TIMEOUT, interval=5, description=f"login redirect of {url}")[0]

    admins = {c: urls[podiumd_env.admin_of(c)] for c in DJANGO_APPS if c in urls}
    return {c: url for c, url in admins.items() if through_keycloak(c, url)}


@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
@pytest.mark.tc("FB-005")
@pytest.mark.source(
    "TA smoke/92-fb-cross-component-sso.spec.ts",
    "One Keycloak login works across PodiumD components: the second component asks for no new login.",
)
def test_one_login_opens_every_admin(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    urls: dict[str, str],
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    sso_admins: dict[str, str],
    component: str,
) -> None:
    """After a Keycloak login at another app's admin, this app's admin needs no new login (TA smoke 92)."""
    keycloak, admins = urls["keycloak"], sso_admins
    if component not in admins:
        pytest.skip(f"{component}'s admin does not log in through Keycloak")
    others = [c for c in admins if admins[c] != admins[component]]
    if not others:
        pytest.skip("no other app's admin logs in through Keycloak")
    need_bootstrap(ADMIN.name)
    page.goto(admins[others[0]] + LOGIN_PATHS[others[0]])
    keycloak_login(page, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
    page.wait_for_url(lambda url: url_host(url) == url_host(admins[others[0]]))
    page.goto(admins[component] + LOGIN_PATHS[component])
    page.wait_for_url(lambda url: url_host(url) == url_host(admins[component]))
    assert not page.url.startswith(realm_url(keycloak, realm_of(podiumd_env))), "Keycloak asked for a new login"
    # A failing OIDC callback also ends on the app's host, on an error page.
    assert in_admin(page.url, admins[component]), f"the login did not reach {component}'s admin: {page.url}"


@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
@pytest.mark.tc("FB-006")
@pytest.mark.source("draaiboek FB-006", "Users can log out, which returns them to the login screen.")
def test_admin_logout_returns_to_the_login(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    urls: dict[str, str],
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    sso_admins: dict[str, str],
    component: str,
) -> None:
    """Logging out of the app's admin ends the session: the admin then asks for a login again."""
    if component not in sso_admins:
        pytest.skip(f"{component}'s admin does not log in through Keycloak")
    admin = sso_admins[component]
    need_bootstrap(ADMIN.name)
    page.goto(admin + LOGIN_PATHS[component])
    keycloak_login(page, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
    page.wait_for_url(lambda url: in_admin(url, admin))
    page.get_by_role("button", name=LOGOUT).or_(page.get_by_role("link", name=LOGOUT)).first.click()
    page.goto(admin + "/admin/")
    assert "login" in page.url or url_host(page.url) == url_host(urls["keycloak"]), f"still in the admin: {page.url}"
