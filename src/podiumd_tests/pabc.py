"""PABC: the decision endpoint (API key) and a browser session for the management API (OIDC cookie)."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.browser import challenge_login
from podiumd_tests.browser import headless_page
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries

if TYPE_CHECKING:
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

DECISION = "/api/v1/application-roles-per-entity-type"
ENTITY_TYPES = "/api/v1/entity-types"


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


def admin_session(env: Environment, username: str, password: str) -> requests.Session:
    """A PABC management session, logged in through headless Chromium: PABC's login needs a page navigation."""
    with headless_page(env) as page:
        return login(page, env, username, password)


def zaaktype_entity_type(pabc: requests.Session, pabc_url: str, omschrijving: str) -> str | None:
    """PABC's id of the ZAAKTYPE entity type of a zaaktype omschrijving, or None."""
    for found in get_entries(pabc, pabc_url + ENTITY_TYPES):
        if found.get("type") == "ZAAKTYPE" and found.get("entityTypeId") == omschrijving:
            return str(found["id"])
    return None


def add_zaaktype_entity_type(pabc: requests.Session, pabc_url: str, omschrijving: str) -> str:
    """Make a zaaktype known to PABC, so roles on all entity types cover it; its id."""
    body = {"entityTypeId": omschrijving, "type": "ZAAKTYPE", "name": omschrijving}
    return str(expect_status(pabc.post(pabc_url + ENTITY_TYPES, json=body), HTTPStatus.CREATED).json()["id"])


def delete_entity_type(pabc: requests.Session, pabc_url: str, entity_type: str) -> None:
    """Delete an entity type by its PABC id."""
    expect_status(pabc.delete(f"{pabc_url}{ENTITY_TYPES}/{entity_type}"), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
