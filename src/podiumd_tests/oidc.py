"""Checks on OIDC login redirects, without logging in."""

from __future__ import annotations

import re

from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from podiumd_tests.responses import expect_status
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    import requests

AUTH_PATH = re.compile(r"^/realms/(?P<realm>[^/]+)/protocol/openid-connect/auth$")
LOGIN_FORM = re.compile(r"""(name|id)=["']username["']""")


class LoginPageError(AssertionError):
    """The response is not Keycloak's login form. An AssertionError, so pytest reports a test failure."""


def keycloak_login_realm(response: requests.Response, keycloak_url: str) -> str:
    """The realm of the Keycloak login form that a redirect chain ended on; LoginPageError otherwise."""
    expect_status(response, HTTPStatus.OK)
    final = urlsplit(response.url)
    if url_host(response.url) != url_host(keycloak_url):
        msg = f"ended on {response.url}, not on Keycloak {keycloak_url}"
        raise LoginPageError(msg)
    match = AUTH_PATH.match(final.path)
    if not match:
        msg = f"not an OIDC auth endpoint: {response.url}"
        raise LoginPageError(msg)
    if not LOGIN_FORM.search(response.text):
        msg = f"no login form on {response.url}"
        raise LoginPageError(msg)
    return match["realm"]
