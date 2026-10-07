"""PABC management API in a logged-in session: roles, domains and applications are configured.

Ported from TA regression 67, 68a, 69 and 71.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KeycloakUser
from podiumd_tests.json_data import entries
from podiumd_tests.pabc import decide
from podiumd_tests.pabc import listed
from podiumd_tests.pabc import login
from podiumd_tests.responses import describe

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import APIRequestContext
    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("pabc", "keycloak")]

# Has PABC's administrator client role (bootstrap step keycloak-user-admin).
ADMIN = KeycloakUser("admin")


@pytest.fixture(name="pabc")
def fixture_pabc(
    page: Page, podiumd_env: Environment, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> APIRequestContext:
    """PABC's management API in the test admin's session."""
    need_bootstrap(ADMIN.name)
    return login(page, urls["pabc"], ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))


def get_list(pabc: APIRequestContext, url: str) -> list[JsonObject]:
    """GET a management list; it must answer 200."""
    response = pabc.get(url)
    assert response.status == HTTPStatus.OK, f"GET {url}: HTTP {response.status}"
    return listed(response.json())


def names(items: list[JsonObject]) -> list[str]:
    """The lowercase names of PABC objects."""
    return [str(i.get("name") or "").lower() for i in items]


def test_functional_roles_are_configured(pabc: APIRequestContext, urls: dict[str, str]) -> None:
    """PABC has at least one functional role (TA reg-67)."""
    assert get_list(pabc, urls["pabc"] + "/api/v1/functional-roles")


def test_application_roles_include_a_handling_role(pabc: APIRequestContext, urls: dict[str, str]) -> None:
    """The application roles include ZAC's behandelaar or KISS's KCC role (TA reg-67)."""
    found = names(get_list(pabc, urls["pabc"] + "/api/v1/application-roles"))
    assert any(word in n for n in found for word in ("behandelaar", "kcc", "medewerker")), found


def test_known_functional_roles_get_application_roles(
    pabc: APIRequestContext, http: requests.Session, urls: dict[str, str], pabc_api_key: str
) -> None:
    """The decision endpoint answers per entity type for configured functional roles (TA reg-68a)."""
    functional = [str(r["name"]) for r in get_list(pabc, urls["pabc"] + "/api/v1/functional-roles")[:3]]
    response = decide(http, urls["pabc"], pabc_api_key, functional)
    assert response.status_code == HTTPStatus.OK, describe(response)
    for result in entries(response.json()["results"]):
        assert isinstance(result.get("applicationRoles"), list), result


def test_entity_types_have_unique_ids(pabc: APIRequestContext, urls: dict[str, str]) -> None:
    """Domains answer, and no entity type was seeded twice (TA reg-69)."""
    get_list(pabc, urls["pabc"] + "/api/v1/domains")
    ids = [str(e["id"]) for e in get_list(pabc, urls["pabc"] + "/api/v1/entity-types")]
    assert len(ids) == len(set(ids)), f"duplicate entity type ids: {sorted(ids)}"


def test_zac_is_a_registered_application(pabc: APIRequestContext, urls: dict[str, str]) -> None:
    """ZAC, PABC's first consumer, is a registered application (TA reg-71)."""
    found = names(get_list(pabc, urls["pabc"] + "/api/v1/applications"))
    assert any("zac" in n or "zaakafhandel" in n for n in found), found
