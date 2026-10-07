"""PABC: the decision endpoint (API key) and a browser session for the management API (OIDC cookie)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.browser import keycloak_login
from podiumd_tests.json_data import entries
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    import requests

    from playwright.sync_api import APIRequestContext
    from playwright.sync_api import Page

    from podiumd_tests.json_data import JsonObject

DECISION = "/api/v1/application-roles-per-entity-type"


def decide(http: requests.Session, pabc_url: str, api_key: str, functional_roles: list[str]) -> requests.Response:
    """POST the decision endpoint: the application roles of these functional role names."""
    return http.post(
        pabc_url + DECISION, json={"FunctionalRoleNames": functional_roles}, headers={"X-API-KEY": api_key}
    )


def login(page: Page, pabc_url: str, username: str, password: str) -> APIRequestContext:
    """Log in to PABC through Keycloak; the page's request context then carries the session cookie.

    PABC answers an anonymous API call with 401 and the Keycloak URL in Location (no redirect),
    and that call sets the OIDC correlation cookies the callback checks.
    """
    challenge = page.request.get(pabc_url + "/api/v1/applications", max_redirects=0)
    location = challenge.headers.get("location")
    if challenge.status != 401 or not location:  # PABC's challenge status
        msg = f"PABC answered {challenge.status} without a login Location to an anonymous API call"
        raise AssertionError(msg)
    page.goto(location)
    keycloak_login(page, username, password)
    page.wait_for_url(lambda url: url_host(url) == url_host(pabc_url))
    me = cast("JsonObject", page.request.get(pabc_url + "/api/me").json())
    if not me.get("isLoggedIn"):
        msg = f"PABC login as {username} kept no session: /api/me says isLoggedIn false"
        raise AssertionError(msg)
    return page.request


def listed(body: object) -> list[JsonObject]:
    """The objects of a PABC list response: a JSON array, or one under results or items."""
    if isinstance(body, dict):
        found = cast("JsonObject", body)
        return entries(found.get("results") or found.get("items"))
    return entries(body)
