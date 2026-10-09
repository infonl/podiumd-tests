"""Keycloak tokens through the OIDC token endpoint. Ported from podiumd-minikube _beheerder_token."""

from __future__ import annotations

import html
import re

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from podiumd_tests.responses import describe

if TYPE_CHECKING:
    import requests


def realm_url(keycloak_url: str, realm: str, path: str = "") -> str:
    """URL of a realm, or of a path below it such as "/protocol/openid-connect/token"."""
    return f"{keycloak_url}/realms/{realm}{path}"


def admin_realm_url(keycloak_url: str, realm: str) -> str:
    """URL of a realm in the Keycloak admin REST API."""
    return f"{keycloak_url}/admin/realms/{realm}"


def discovery_url(keycloak_url: str, realm: str) -> str:
    """URL of a realm's OIDC discovery document."""
    return realm_url(keycloak_url, realm, "/.well-known/openid-configuration")


class TokenError(Exception):
    """Keycloak did not return an access token."""


@dataclass(frozen=True)
class PasswordLogin:
    """A user login through one Keycloak client."""

    client_id: str
    username: str
    password: str
    client_secret: str | None = None


def password_grant(session: requests.Session, keycloak_url: str, realm: str, login: PasswordLogin) -> str:
    """Access token for a user, through the resource-owner password grant."""
    data = {"grant_type": "password", "client_id": login.client_id, "scope": "openid"}
    data |= {"username": login.username, "password": login.password}
    if login.client_secret:
        data["client_secret"] = login.client_secret
    response = session.post(realm_url(keycloak_url, realm, "/protocol/openid-connect/token"), data=data)
    if response.status_code != HTTPStatus.OK:
        msg = f"token request for {login.username!r} in realm {realm!r} failed: {describe(response)}"
        raise TokenError(msg)
    token: object = response.json().get("access_token")
    if not isinstance(token, str):
        msg = f"token response for {login.username!r} has no access_token"
        raise TokenError(msg)
    return token


def form_login(http: requests.Session, start_url: str, username: str, password: str) -> requests.Response:
    """Log in through Keycloak's login form without a browser; start_url redirects there. The app's final response.

    For apps that accept only their own session (code flow), such as ZAC's REST API.
    """
    page = http.get(start_url)
    form = re.search(r'<form[^>]*id="kc-form-login"[^>]*>', page.text)
    action = re.search(r'action="([^"]+)"', form[0]) if form else None
    if action is None:
        msg = f"no Keycloak login form at {page.url}"
        raise TokenError(msg)
    response = http.post(html.unescape(action[1]), data={"username": username, "password": password})
    if 'id="kc-form-login"' in response.text:
        msg = f"Keycloak refused the login of {username!r}"
        raise TokenError(msg)
    return response
