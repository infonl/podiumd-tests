"""PABC management API in a logged-in session: roles, domains and applications are configured.

Ported from TA regression 67, 68a, 69 and 71.
"""

from __future__ import annotations

import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import ZAC_APPLICATION
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.pabc import DOMAINS
from podiumd_tests.pabc import ENTITY_TYPES
from podiumd_tests.pabc import add_zaaktype_entity_type
from podiumd_tests.pabc import decide
from podiumd_tests.pabc import delete_entity_type
from podiumd_tests.pabc import delete_roles_and_domain
from podiumd_tests.pabc import ensure_domain
from podiumd_tests.pabc import ensure_functional_role
from podiumd_tests.pabc import login
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("pabc", "keycloak")]

# Has PABC's administrator client role (bootstrap step keycloak-user-admin).


@pytest.fixture(name="pabc")
def fixture_pabc(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """PABC's management API in the test admin's session."""
    need_bootstrap(ADMIN.name)
    return login(page, podiumd_env, ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))


def names(items: list[JsonObject]) -> list[str]:
    """The lowercase names of PABC objects."""
    return [str(i.get("name") or "").lower() for i in items]


@pytest.mark.source(
    "TA regression/67-pabc-functional-roles.spec.ts",
    "PABC has the functional roles seeded, and the base roles ZAC and KISS expect.",
)
@pytest.mark.scenario("""
    Given the test admin is logged in to PABC
    When the admin lists the functional roles
    Then PABC has at least one functional role
""")
def test_functional_roles_are_configured(pabc: requests.Session, urls: dict[str, str]) -> None:
    """PABC has at least one functional role (TA reg-67)."""
    assert get_entries(pabc, f"{urls['pabc']}/api/v1/functional-roles")


@pytest.mark.source(
    "TA regression/67-pabc-functional-roles.spec.ts",
    "PABC has the functional roles seeded, and the base roles ZAC and KISS expect.",
)
@pytest.mark.scenario("""
    Given the test admin is logged in to PABC
    When the admin lists the application roles
    Then they include a behandelaar, KCC or medewerker role
""")
def test_application_roles_include_a_handling_role(pabc: requests.Session, urls: dict[str, str]) -> None:
    """The application roles include ZAC's behandelaar or KISS's KCC role (TA reg-67)."""
    found = names(get_entries(pabc, f"{urls['pabc']}/api/v1/application-roles"))
    assert any(word in n for n in found for word in ("behandelaar", "kcc", "medewerker")), found


@pytest.mark.source(
    "TA regression/68-pabc-decision.spec.ts",
    "PABC's decision endpoint maps functional roles to application roles per entity type, the core of PBAC.",
)
@pytest.mark.scenario("""
    Given the test admin is logged in to PABC
    And a client with PABC's API key
    When the client asks PABC's decision endpoint for up to three configured functional roles
    Then PABC answers with a list of application roles per entity type
""")
def test_known_functional_roles_get_application_roles(
    pabc: requests.Session, http: requests.Session, urls: dict[str, str], pabc_api_key: str
) -> None:
    """The decision endpoint answers per entity type for configured functional roles (TA reg-68a)."""
    functional = [str(role["name"]) for role in get_entries(pabc, f"{urls['pabc']}/api/v1/functional-roles")[:3]]
    response = decide(http, urls["pabc"], pabc_api_key, functional)
    assert response.status_code == HTTPStatus.OK, describe(response)
    for result in entries(response.json()["results"]):
        assert isinstance(result.get("applicationRoles"), list), result


@pytest.mark.source(
    "TA regression/69-pabc-domains-entity-types.spec.ts",
    "PABC's domains and entity types answer and are consistent, with no orphaned references.",
)
@pytest.mark.scenario("""
    Given the test admin is logged in to PABC
    When the admin lists the domains and the entity types
    Then PABC answers both lists
    And no entity type is listed twice
""")
def test_entity_types_have_unique_ids(pabc: requests.Session, urls: dict[str, str]) -> None:
    """Domains answer, and no entity type was seeded twice (TA reg-69)."""
    get_entries(pabc, f"{urls['pabc']}/api/v1/domains")
    ids = [str(entity_type["id"]) for entity_type in get_entries(pabc, f"{urls['pabc']}/api/v1/entity-types")]
    assert len(ids) == len(set(ids)), f"duplicate entity type ids: {sorted(ids)}"


@pytest.mark.source(
    "TA regression/71-pabc-zac-integration-coherence.spec.ts",
    "ZAC must be registered in PABC, else every ZAC login gets no roles.",
)
@pytest.mark.scenario("""
    Given the test admin is logged in to PABC
    When the admin lists the applications
    Then ZAC is a registered application
""")
def test_zac_is_a_registered_application(pabc: requests.Session, urls: dict[str, str]) -> None:
    """ZAC, PABC's first consumer, is a registered application (TA reg-71)."""
    found = names(get_entries(pabc, f"{urls['pabc']}/api/v1/applications"))
    assert any("zac" in n or "zaakafhandel" in n for n in found), found


@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, autorisatie-iam):"
    " create and delete a domein in PABC.",
)
@pytest.mark.scenario("""
    Given a new domain in PABC with an entity type and a functional role mapped in it
    When the admin deletes the domain
    Then PABC refuses it, and the domain stays
    When the admin deletes the functional role and then the domain
    Then PABC no longer lists the domain
    And the entity type stays
""")
def test_domain_is_deleted_once_no_functional_role_uses_it(
    pabc: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """PABC answers 422 to deleting a domain with a mapping; without one it deletes the domain, not its entity types."""
    pabc_url = urls["pabc"]
    name = registry.tagged(f"pabc-{secrets.token_hex(3)}")
    entity_type = add_zaaktype_entity_type(pabc, pabc_url, name)
    registry.add(f"PABC entity type {name}", lambda: delete_entity_type(pabc, pabc_url, entity_type))
    domain = ensure_domain(pabc, pabc_url, name, [entity_type])
    registry.add(f"PABC domain {name}", lambda: delete_roles_and_domain(pabc, pabc_url, [name], name))
    ensure_functional_role(pabc, pabc_url, name, ZAC_APPLICATION, ("behandelaar",), domain)

    def domains() -> list[object]:
        return [found.get("name") for found in get_entries(pabc, pabc_url + DOMAINS)]

    refused = pabc.delete(f"{pabc_url}{DOMAINS}/{domain}")
    assert refused.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, describe(refused)
    assert name in domains()
    delete_roles_and_domain(pabc, pabc_url, [name], name)
    assert name not in domains()
    assert entity_type in [str(found["id"]) for found in get_entries(pabc, pabc_url + ENTITY_TYPES)]


@pytest.mark.source(
    "TA smoke/66-pabc-health.spec.ts",
    "PABC, which gives ZAC its PBAC decisions, is reachable and enforces its API key.",
)
@pytest.mark.scenario("""
    Given the test admin is logged in to PABC
    When the admin asks for PABC's version
    Then PABC answers with its version and revision
""")
def test_app_version_is_shown_after_login(pabc: requests.Session, urls: dict[str, str]) -> None:
    """PABC tells a logged-in user its version and revision (TA smoke 66)."""
    version = expect_status(pabc.get(f"{urls['pabc']}/api/app-version"), HTTPStatus.OK).json()
    assert version["version"]
    assert version["revision"]
