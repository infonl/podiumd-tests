"""PABC: the decision endpoint (API key) and a browser session for the management API (OIDC cookie)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.browser import challenge_login
from podiumd_tests.json_data import entries

if TYPE_CHECKING:
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

DECISION = "/api/v1/application-roles-per-entity-type"


def decide(http: requests.Session, pabc_url: str, api_key: str, functional_roles: list[str]) -> requests.Response:
    """POST the decision endpoint: the application roles of these functional role names."""
    return http.post(
        pabc_url + DECISION, json={"FunctionalRoleNames": functional_roles}, headers={"X-API-KEY": api_key}
    )


def login(page: Page, env: Environment, username: str, password: str) -> requests.Session:
    """Log in to PABC through Keycloak; AssertionError when PABC keeps no session."""
    pabc_url = env.profile.urls["pabc"]
    api = challenge_login(page, env, pabc_url, username, password)
    me = cast("JsonObject", api.get(pabc_url + "/api/me").json())
    if not me.get("isLoggedIn"):
        msg = f"PABC login as {username} kept no session: /api/me says isLoggedIn false"
        raise AssertionError(msg)
    return api


def listed(body: object) -> list[JsonObject]:
    """The objects of a PABC list response: a JSON array, or one under results or items."""
    if isinstance(body, dict):
        found = cast("JsonObject", body)
        return entries(found.get("results") or found.get("items"))
    return entries(body)
