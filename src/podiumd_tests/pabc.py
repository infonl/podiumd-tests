"""PABC: the decision endpoint (API key) and a browser session for the management API (OIDC cookie)."""

from __future__ import annotations

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


def ensure_domain(pabc: requests.Session, pabc_url: str, name: str, entity_types: list[str]) -> str:
    """The domain of this name, created if missing, holding these entity types (PABC ids); its id."""
    found = next((d for d in get_entries(pabc, pabc_url + DOMAINS) if d.get("name") == name), None)
    if found is None:
        body = {"name": name, "description": "podiumd-tests"}
        found = cast("JsonObject", expect_status(pabc.post(pabc_url + DOMAINS, json=body), HTTPStatus.CREATED).json())
    domain = str(found["id"])
    for entity_type in set(entity_types) - set(strings(found.get("entityTypes"))):
        expect_status(pabc.post(f"{pabc_url}{DOMAINS}/{domain}/entity-types/{entity_type}"), HTTPStatus.NO_CONTENT)
    return domain


def ensure_functional_role(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # one mapping set
    pabc: requests.Session, pabc_url: str, name: str, application: str, roles: tuple[str, ...], domain: str
) -> None:
    """The functional role of this name, created if missing, mapped to these application roles in the domain."""
    found = next((r for r in get_entries(pabc, pabc_url + FUNCTIONAL_ROLES) if r.get("name") == name), None)
    if found is None:
        response = pabc.post(pabc_url + FUNCTIONAL_ROLES, json={"name": name})
        found = cast("JsonObject", expect_status(response, HTTPStatus.CREATED).json())
    mapped = {str(m.get("applicationRoleId")) for m in entries(found.get("mappings")) if m.get("domain")}
    for role in get_entries(pabc, pabc_url + APPLICATION_ROLES):
        if role.get("name") in roles and role.get("application") == application and str(role["id"]) not in mapped:
            body = {"applicationRoleId": role["id"], "domainId": domain, "isAllEntityTypes": False}
            expect_status(
                pabc.post(f"{pabc_url}{FUNCTIONAL_ROLES}/{found['id']}/mappings", json=body), HTTPStatus.CREATED
            )


def domain_mappings(pabc: requests.Session, pabc_url: str, role: str) -> int:
    """How many mappings to a single domain the functional role of this name has; 0 when it does not exist."""
    roles = [r for r in get_entries(pabc, pabc_url + FUNCTIONAL_ROLES) if r.get("name") == role]
    return sum(1 for r in roles for m in entries(r.get("mappings")) if m.get("domain"))


def delete_functional_role_and_domain(pabc: requests.Session, pabc_url: str, role: str, domain: str) -> None:
    """Delete the functional role (with its mappings) and then the domain of these names, where they exist."""
    for path, name in ((FUNCTIONAL_ROLES, role), (DOMAINS, domain)):
        for found in get_entries(pabc, pabc_url + path):
            if found.get("name") == name:
                expect_status(pabc.delete(f"{pabc_url}{path}/{found['id']}"), HTTPStatus.OK, HTTPStatus.NO_CONTENT)


def mapped_application_roles(decision: JsonObject, entity_type: str) -> set[str]:
    """The application roles a decision of PABC gives for an entity type (its entityTypeId)."""
    return {
        str(role.get("name"))
        for result in entries(decision.get("results"))
        if section(result, "entityType").get("id") == entity_type
        for role in entries(result.get("applicationRoles"))
    }
