"""Is login wired to Keycloak? Without logging in: follow the redirects to the login page.

Ported from TA/EX smoke 82 (portaal login config), 05a (DigiD link),
99 test 1 (eHerkenning link), 81 (Keycloak realm) and the first leg of MK/PI
test_login_flow.py. The realm is read from the redirect, not configured.
"""

from __future__ import annotations

import re

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak import discovery_url
from podiumd_tests.auth.keycloak import realm_url
from podiumd_tests.components import DJANGO_APPS
from podiumd_tests.oidc import LOGIN_PATHS
from podiumd_tests.oidc import NAVIGATE
from podiumd_tests.oidc import keycloak_hosts
from podiumd_tests.oidc import keycloak_login_realm
from podiumd_tests.oidc import logs_in_through_keycloak
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment

pytestmark = pytest.mark.smoke


@pytest.mark.source(
    "TA smoke/81-continuiteit-pings.spec.ts",
    "Continuity pings: every PodiumD component, Keycloak's realm included, answers through its ingress within 5 s.",
)
@pytest.mark.source(
    "EX tests/smoke/81-continuiteit-pings.spec.ts",
    "Continuity pings: every PodiumD component, Keycloak's realm included, answers through its ingress within 5 s.",
)
@pytest.mark.requires("keycloak")
def test_keycloak_discovery(http: requests.Session, urls: dict[str, str]) -> None:
    """The master realm publishes its OIDC configuration."""
    response = expect_status(http.get(discovery_url(urls["keycloak"], "master")), HTTPStatus.OK)
    assert str(response.json()["issuer"]).endswith(realm_url("", "master"))


@pytest.mark.source(
    "MK test_login_flow.py",
    "End-to-end OIDC login through ZAC, replaying the browser's redirects: ZAC, Keycloak and PABC are wired together.",
)
@pytest.mark.source(
    "PI test_login_flow.py",
    "End-to-end OIDC login through ZAC adapted from podiumd-minikube, following real redirects to real hostnames.",
)
@pytest.mark.source(
    "podiumd-tests",
    "Every app's login: a Keycloak scope fault in KISS and ITA passed while only ZAC and Open Inwoner were checked.",
)
@pytest.mark.requires("keycloak")
@pytest.mark.parametrize("component", [requiring(c, c) for c in LOGIN_PATHS])
def test_login_ends_on_the_keycloak_form(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment, component: str
) -> None:
    """Starting the app's login ends on Keycloak's login form: Keycloak accepts its client, redirect URI and scopes."""
    start, hosts = urls[podiumd_env.admin_of(component)] + LOGIN_PATHS[component], keycloak_hosts(urls)
    if component in DJANGO_APPS and not logs_in_through_keycloak(http, start, hosts):
        pytest.skip(f"{component}'s admin does not log in through Keycloak")
    keycloak_login_realm(http.get(start, headers=NAVIGATE), hosts)


@pytest.mark.source(
    "podiumd-tests",
    "On Open Object the objecttypen host must start the admin login too; the other login test uses the objecten host.",
)
@pytest.mark.requires("keycloak", "objecttypen")
# Not strict: an edge may redirect the login to the objecten host (podiumd-infra loginRedirectHost).
@pytest.mark.xfail(
    strict=False,
    raises=AssertionError,
    reason="[podiumd-chart-5] podiumd 4.10.0: Keycloak client objecten accepts only the objecten host as redirect URI,"
    " so the admin login on the objecttypen host answers 400; not yet reported upstream",
)
def test_admin_login_on_the_objecttypen_host_ends_on_the_keycloak_form(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment
) -> None:
    """On Open Object the objecttypen host still starts the admin login."""
    if podiumd_env.admin_of("objecttypen") == "objecttypen":
        pytest.skip("objecttypen has its own admin")
    start = urls["objecttypen"] + LOGIN_PATHS["objecttypen"]
    keycloak_login_realm(http.get(start, headers=NAVIGATE), keycloak_hosts(urls))


@pytest.mark.source(
    "TA smoke/82-portaal-login-config.spec.ts",
    "Portal login page exposes the expected login routes: DigiD OIDC, 'Log in met DigiD' and the Keycloak redirect.",
)
@pytest.mark.source(
    "EX tests/smoke/82-portaal-login-config.spec.ts",
    "Portal login page exposes the expected login routes: DigiD OIDC, 'Log in met DigiD' and the Keycloak redirect.",
)
@pytest.mark.source(
    "TA smoke/05-portaal-digid-login.spec.ts",
    "Portal login route and DigiD OIDC flow: the login page shows a DigiD button and the login goes through Keycloak.",
)
@pytest.mark.source(
    "EX tests/smoke/05-portaal-digid-login.spec.ts",
    "Portal login route and DigiD OIDC flow: the login page shows a DigiD button and the login goes through Keycloak.",
)
@pytest.mark.source(
    "TA smoke/99-portaal-eherkenning-login.spec.ts",
    "Portal eHerkenning OIDC login via the Keycloak mock: the login page shows the eHerkenning button.",
)
@pytest.mark.source(
    "EX tests/smoke/99-portaal-eherkenning-login.spec.ts",
    "Portal eHerkenning OIDC login via the Keycloak mock: the login page shows the eHerkenning button.",
)
@pytest.mark.requires("openinwoner")
@pytest.mark.tc("ARCH-019")
def test_portaal_login_page_offers_digid_and_eherkenning(http: requests.Session, urls: dict[str, str]) -> None:
    """The Open Inwoner login page has the theme and both login options (82, 05a, 99)."""
    response = expect_status(http.get(urls["openinwoner"] + "/accounts/login/"), HTTPStatus.OK)
    html = response.text
    assert "openinwoner-theme" in html
    assert "/digid-oidc/authenticate/" in html, "no DigiD login link"
    assert "/eherkenning-oidc/authenticate/" in html, "no eHerkenning login link"
    assert re.search(r"Log in met DigiD", html, re.IGNORECASE), "no 'Log in met DigiD' text"


@pytest.mark.source(
    "TA smoke/82-portaal-login-config.spec.ts",
    "Portal login page exposes the expected login routes: DigiD OIDC, 'Log in met DigiD' and the Keycloak redirect.",
)
@pytest.mark.source(
    "EX tests/smoke/82-portaal-login-config.spec.ts",
    "Portal login page exposes the expected login routes: DigiD OIDC, 'Log in met DigiD' and the Keycloak redirect.",
)
@pytest.mark.source(
    "TA smoke/05-portaal-digid-login.spec.ts",
    "Portal login route and DigiD OIDC flow: the login page shows a DigiD button and the login goes through Keycloak.",
)
@pytest.mark.source(
    "EX tests/smoke/05-portaal-digid-login.spec.ts",
    "Portal login route and DigiD OIDC flow: the login page shows a DigiD button and the login goes through Keycloak.",
)
@pytest.mark.source(
    "TA smoke/99-portaal-eherkenning-login.spec.ts",
    "Portal eHerkenning OIDC login via the Keycloak mock: the login page shows the eHerkenning button.",
)
@pytest.mark.source(
    "EX tests/smoke/99-portaal-eherkenning-login.spec.ts",
    "Portal eHerkenning OIDC login via the Keycloak mock: the login page shows the eHerkenning button.",
)
@pytest.mark.requires("openinwoner", "keycloak")
@pytest.mark.parametrize("method", ["digid", "eherkenning"])
def test_portaal_login_redirects_to_keycloak(http: requests.Session, urls: dict[str, str], method: str) -> None:
    """Starting a DigiD or eHerkenning login ends on the Keycloak login form (82 test 4, 05b and 99 first leg)."""
    keycloak_login_realm(http.get(f"{urls['openinwoner']}/{method}-oidc/authenticate/?next=/"), keycloak_hosts(urls))
