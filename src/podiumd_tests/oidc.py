"""Checks on OIDC login redirects, without logging in."""

from __future__ import annotations

import re

from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from podiumd_tests.auth.keycloak import login_form_action
from podiumd_tests.components import DJANGO_APPS
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import is_server_error
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from collections.abc import Collection
    from collections.abc import Mapping

    import requests

AUTH_PATH = re.compile(r"^/realms/(?P<realm>[^/]+)/protocol/openid-connect/auth$")
LOGIN_FORM = re.compile(r"""(name|id)=["']username["']""")

# Where an app's login starts. A Django admin may log in through Keycloak or only locally.
CHALLENGE = "/api/challenge?returnUrl=%2F"
AUTHENTICATE = "/oidc/authenticate/?next=/admin/"
LOGIN_PATHS = {
    **dict.fromkeys(DJANGO_APPS, AUTHENTICATE),
    "zac": "/",
    "kiss": CHALLENGE,
    "ita": CHALLENGE,
    "pabc": CHALLENGE,
    "openbeheer": "/auth/oidc/authenticate/?next=/",
}
# An app with one replica busy with browser logins (Open Formulieren on kees00) can take longer than
# the session's default timeout to send its login redirect.
LOGIN_REDIRECT_TIMEOUT = 60
# A browser page navigation: ITA and PABC answer any other request on CHALLENGE with 401.
NAVIGATE = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}


class LoginPageError(AssertionError):
    """The response is not Keycloak's login form. An AssertionError, so pytest reports a test failure."""


def keycloak_hosts(urls: Mapping[str, str]) -> frozenset[str]:
    """Hosts of Keycloak: apps log in through keycloak, Django admins on some estates through keycloak-admin."""
    return frozenset(url_host(urls[c]) for c in ("keycloak", "keycloak-admin") if c in urls)


def logs_in_through_keycloak(http: requests.Session, start_url: str, hosts: Collection[str]) -> bool:
    """Whether the login at start_url redirects to Keycloak; UnexpectedStatusError for a server error.

    A failing app must fail the test, not look like an app without a Keycloak login.
    """
    response = http.get(start_url, allow_redirects=False, timeout=LOGIN_REDIRECT_TIMEOUT)
    if is_server_error(response):
        msg = f"{describe(response)}: the app fails instead of answering its login"
        raise UnexpectedStatusError(msg)
    return response.is_redirect and url_host(response.headers["Location"]) in hosts


def keycloak_login_realm(response: requests.Response, hosts: Collection[str]) -> str:
    """The realm of the Keycloak login form that a redirect chain ended on; LoginPageError otherwise.

    Keycloak sends a client it refuses (unknown redirect URI, invalid_scope) back to the app or to an error page.
    A form that posts to another host (the realm's frontendUrl) cannot log in.
    """
    expect_status(response, HTTPStatus.OK)
    final = urlsplit(response.url)
    if url_host(response.url) not in hosts:
        msg = f"ended on {response.url}, not on Keycloak ({', '.join(sorted(hosts))})"
        raise LoginPageError(msg)
    match = AUTH_PATH.match(final.path)
    if not match:
        msg = f"not an OIDC auth endpoint: {response.url}"
        raise LoginPageError(msg)
    if not LOGIN_FORM.search(response.text):
        msg = f"no login form on {response.url}"
        raise LoginPageError(msg)
    action = login_form_action(response.text)
    if action and url_host(action) != url_host(response.url):
        # Keycloak then misses its login cookie: "Restart login cookie not found".
        msg = f"login form on {url_host(response.url)} posts to {url_host(action)}"
        raise LoginPageError(msg)
    return match["realm"]
