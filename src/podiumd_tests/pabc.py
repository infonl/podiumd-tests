"""PABC: the decision endpoint (API key) and a browser session for the management API (OIDC cookie)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.browser import challenge_login
from podiumd_tests.browser import headless_page
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries

if TYPE_CHECKING:
    from collections.abc import Iterable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

DECISION = "/api/v1/application-roles-per-entity-type"
ENTITY_TYPES = "/api/v1/entity-types"
DOMAINS = "/api/v1/domains"
FUNCTIONAL_ROLES = "/api/v1/functional-roles"
APPLICATION_ROLES = "/api/v1/application-roles"


def decide(http: requests.Session, pabc_url: str, api_key: str, functional_roles: list[str]) -> requests.Response:
    """POST the decision endpoint: the application roles of these functional role names."""
    return http.post(
        pabc_url + DECISION, json={"FunctionalRoleNames": functional_roles}, headers={"X-API-KEY": api_key}
    )


def login(page: Page, env: Environment, username: str, password: str) -> requests.Session:
    """Log in to PABC through Keycloak; AssertionError when PABC keeps no session."""
    pabc_url = env.profile.urls["pabc"]
    api = challenge_login(page, env, pabc_url, username, password)
    me = cast("JsonObject", api.get(f"{pabc_url}/api/me").json())
    if not me.get("isLoggedIn"):
        msg = f"PABC login as {username} kept no session: /api/me says isLoggedIn false"
        raise AssertionError(msg)
    return api


def admin_session(env: Environment, username: str, password: str) -> requests.Session:
    """Return a PABC management session, logged in through headless Chromium: PABC's login needs a page navigation.

    The login runs in its own thread: Playwright's sync API refuses a thread with a running asyncio loop, which a
    pytest worker has after a browser test (bootstrap checks of need_bootstrap).
    """

    def log_in() -> requests.Session:
        with headless_page(env) as page:
            return login(page, env, username, password)

    with ThreadPoolExecutor(max_workers=1) as thread:
        return thread.submit(log_in).result()


def zaaktype_entity_type(pabc: requests.Session, pabc_url: str, omschrijving: str) -> str | None:
    """PABC's id of the ZAAKTYPE entity type of a zaaktype omschrijving, or None."""
    for found in get_entries(pabc, pabc_url + ENTITY_TYPES):
        if found.get("type") == "ZAAKTYPE" and found.get("entityTypeId") == omschrijving:
            return str(found["id"])
    return None


def add_zaaktype_entity_type(pabc: requests.Session, pabc_url: str, omschrijving: str) -> str:
    """Make a zaaktype known to PABC, so roles on all entity types cover it; its id."""
    body = {"entityTypeId": omschrijving, "type": "ZAAKTYPE", "name": omschrijving}
    response = pabc.post(pabc_url + ENTITY_TYPES, json=body)
    return str(expect_status(response, HTTPStatus.CREATED).json()["id"])


def delete_entity_type(pabc: requests.Session, pabc_url: str, entity_type: str) -> None:
    """Delete an entity type by its PABC id."""
    expect_status(pabc.delete(f"{pabc_url}{ENTITY_TYPES}/{entity_type}"), HTTPStatus.OK, HTTPStatus.NO_CONTENT)


def ensure_domain(pabc: requests.Session, pabc_url: str, name: str, entity_types: list[str]) -> str:
    """Return the domain of this name, created if missing, holding these entity types (PABC ids); its id."""
    domains = get_entries(pabc, pabc_url + DOMAINS)
    found = next((existing for existing in domains if existing.get("name") == name), None)
    if found is None:
        response = pabc.post(pabc_url + DOMAINS, json={"name": name, "description": "podiumd-tests"})
        found = cast("JsonObject", expect_status(response, HTTPStatus.CREATED).json())
    domain = str(found["id"])
    for entity_type in set(entity_types) - set(strings(found.get("entityTypes"))):
        expect_status(pabc.post(f"{pabc_url}{DOMAINS}/{domain}/entity-types/{entity_type}"), HTTPStatus.NO_CONTENT)
    return domain


def application_roles(pabc: requests.Session, pabc_url: str, application: str) -> list[JsonObject]:
    """PABC's application roles of an application."""
    return [role for role in get_entries(pabc, pabc_url + APPLICATION_ROLES) if role.get("application") == application]


def ensure_functional_role(  # noqa: PLR0913, PLR0917  # one mapping set
    pabc: requests.Session, pabc_url: str, name: str, application: str, roles: tuple[str, ...], domain: str
) -> None:
    """Ensure the functional role of this name, mapped to these application roles in the domain."""
    known = application_roles(pabc, pabc_url, application)
    missing = set(roles) - {str(role.get("name")) for role in known}
    if missing:
        msg = f"PABC has no application role {', '.join(sorted(missing))} of {application}: add it to PABC's dataset"
        raise LookupError(msg)
    found = next(
        (existing for existing in get_entries(pabc, pabc_url + FUNCTIONAL_ROLES) if existing.get("name") == name), None
    )
    if found is None:
        response = pabc.post(pabc_url + FUNCTIONAL_ROLES, json={"name": name})
        found = cast("JsonObject", expect_status(response, HTTPStatus.CREATED).json())
    mapped = {
        str(mapping.get("applicationRoleId")) for mapping in entries(found.get("mappings")) if mapping.get("domain")
    }
    for role in known:
        if role.get("name") in roles and str(role["id"]) not in mapped:
            body = {"applicationRoleId": role["id"], "domainId": domain, "isAllEntityTypes": False}
            expect_status(
                pabc.post(f"{pabc_url}{FUNCTIONAL_ROLES}/{found['id']}/mappings", json=body), HTTPStatus.CREATED
            )


def domain_mappings(pabc: requests.Session, pabc_url: str, role: str) -> int:
    """How many mappings to a single domain the functional role of this name has; 0 when it does not exist."""
    roles = [found for found in get_entries(pabc, pabc_url + FUNCTIONAL_ROLES) if found.get("name") == role]
    return sum(1 for found in roles for mapping in entries(found.get("mappings")) if mapping.get("domain"))


def delete_roles_and_domain(pabc: requests.Session, pabc_url: str, roles: Iterable[str], domain: str) -> None:
    """Delete the functional roles (with their mappings) and then the domain of these names, where they exist."""
    for path, names in ((FUNCTIONAL_ROLES, set(roles)), (DOMAINS, {domain})):
        for found in get_entries(pabc, pabc_url + path):
            if found.get("name") in names:
                expect_status(pabc.delete(f"{pabc_url}{path}/{found['id']}"), HTTPStatus.OK, HTTPStatus.NO_CONTENT)


def mapped_application_roles(decision: JsonObject, entity_type: str) -> set[str]:
    """Return the application roles a decision of PABC gives for an entity type (its entityTypeId)."""
    return {
        str(role.get("name"))
        for result in entries(decision.get("results"))
        if section(result, "entityType").get("id") == entity_type
        for role in entries(result.get("applicationRoles"))
    }
