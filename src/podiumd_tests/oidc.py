"""Checks on OIDC login redirects, without logging in."""

from __future__ import annotations

import re

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    import requests

AUTH_PATH = re.compile(r"^/realms/(?P<realm>[^/]+)/protocol/openid-connect/auth$")
LOGIN_FORM = re.compile(r"""(name|id)=["']username["']""")


class LoginPageError(AssertionError):
    """The response is not Keycloak's login form. An AssertionError, so pytest reports a test failure."""


def keycloak_login_realm(response: requests.Response, keycloak_url: str) -> str:
    """The realm of the Keycloak login form that a redirect chain ended on; LoginPageError otherwise."""
    if response.status_code != 200:  # HTTP OK
        msg = f"{response.url}: HTTP {response.status_code}"
        raise LoginPageError(msg)
    final = urlsplit(response.url)
    if final.hostname != urlsplit(keycloak_url).hostname:
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
