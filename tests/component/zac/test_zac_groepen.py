"""ZAC and changes to Keycloak groups, on run-tagged groups and users of podiumd-tests.

ZAC 5.9.1 reads groups and their members from Keycloak on every request: a group's name is its id in ZAC, its
description its naam, and attribute active false makes it inactive.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.zac import active_groups
from podiumd_tests.zac import assignment
from podiumd_tests.zac import group_members
from podiumd_tests.zac import open_task
from podiumd_tests.zac import read_taak
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import start_human_task
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import toekennen_taak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    # pabc and cluster: fixture zac_taken_zaak's throwaway zaaktype.
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster"),
    pytest.mark.xdist_group("zac-taken-zaaktype"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, taken-cmmn and"
        " autorisatie-iam): Keycloak group changes.",
    ),
]

AANVULLENDE_INFORMATIE = "Aanvullende informatie"


def _keycloak(env: Environment) -> KeycloakAdmin:
    """A Keycloak admin with a fresh token: the master realm's tokens expire within minutes."""
    return for_environment(env)


def _group_id(env: Environment, group: str) -> str:
    """The Keycloak id of the group."""
    return str(_keycloak(env).group_id(group))


def _zaak_and_taak(
    zac: requests.Session, zac_url: str, zac_taken_zaak: Callable[[], JsonObject], group: str
) -> tuple[JsonObject, JsonObject]:
    """A zaak assigned to the group, with the taak Aanvullende informatie for the group."""
    zaak = zac_taken_zaak()
    expect_status(toekennen(zac, zac_url, zaak, group, None), HTTPStatus.OK)
    response = start_human_task(zac, zac_url, zaak, AANVULLENDE_INFORMATIE, group)
    expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    return zaak, open_task(zac, zac_url, str(zaak["uuid"]), AANVULLENDE_INFORMATIE)


def _groepen(zac: requests.Session, zac_url: str, zaak: JsonObject, taak: JsonObject) -> tuple[JsonObject, JsonObject]:
    """The groep of the zaak and of the taak, as ZAC shows them now."""
    zaak_groep = section(read_zaak(zac, zac_url, str(zaak["uuid"])), "groep")
    return zaak_groep, section(read_taak(zac, zac_url, str(taak["id"])), "groep")


@pytest.mark.requires("mailpit")
@pytest.mark.scenario("""
    Given a new Keycloak group with a new user as member
    Then ZAC offers the group, and the user as behandelaar in it
    And a zaak can be assigned to the group and the user
    When the user leaves the group in Keycloak
    Then ZAC no longer offers the user in the group
    And refuses to assign the zaak to the group and the user
""")
def test_new_group_and_its_members_show_in_zac(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    zac_taken_zaak: Callable[[], JsonObject],
    registry: ResourceRegistry,
) -> None:
    """ZAC's group list, a group's behandelaars and toekennen follow Keycloak's groups and memberships."""
    zac_url = urls["zac"]
    group = make_role_group(podiumd_env, registry, "behandelaar")
    lid, _ = make_group_member(podiumd_env, registry, group)
    assert group in active_groups(zac, zac_url)
    assert lid in group_members(zac, zac_url, group)
    zaak = zac_taken_zaak()
    assigned = expect_status(toekennen(zac, zac_url, zaak, group, lid), HTTPStatus.OK).json()
    assert assignment(assigned) == (group, lid)

    keycloak = _keycloak(podiumd_env)
    keycloak.leave_group(str(keycloak.user_id(lid)), _group_id(podiumd_env, group))
    assert lid not in group_members(zac, zac_url, group)
    expect_status(toekennen(zac, zac_url, zaak, group, lid), HTTPStatus.BAD_REQUEST)


@pytest.mark.scenario("""
    Given a zaak and its taak Aanvullende informatie assigned to a new Keycloak group
    When the group gets a new description in Keycloak
    Then the zaak and the taak show the group with that description as its name
    When the group is set inactive in Keycloak
    Then ZAC no longer offers the group, and the zaak and the taak show it as inactive
    When the group is set active again
    Then ZAC offers the group again
""")
def test_renamed_and_inactive_group_shows_on_its_zaak_and_taak(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    zac_taken_zaak: Callable[[], JsonObject],
    registry: ResourceRegistry,
) -> None:
    """ZAC resolves a zaak's and taak's group by its name: a new description and active false show at once."""
    zac_url = urls["zac"]
    group = make_role_group(podiumd_env, registry, "behandelaar")
    zaak, taak = _zaak_and_taak(zac, zac_url, zac_taken_zaak, group)
    naam = f"{group} hernoemd"

    _keycloak(podiumd_env).update_group(_group_id(podiumd_env, group), description=naam)
    zaak_groep, taak_groep = _groepen(zac, zac_url, zaak, taak)
    assert zaak_groep == taak_groep == {"id": group, "naam": naam, "active": True}

    _keycloak(podiumd_env).update_group(_group_id(podiumd_env, group), attributes={"active": ["false"]})
    assert group not in active_groups(zac, zac_url)
    zaak_groep, taak_groep = _groepen(zac, zac_url, zaak, taak)
    assert zaak_groep == taak_groep == {"id": group, "naam": naam, "active": False}

    _keycloak(podiumd_env).update_group(_group_id(podiumd_env, group), attributes={"active": ["true"]})
    assert group in active_groups(zac, zac_url)


@pytest.mark.scenario("""
    Given a zaak and its taak Aanvullende informatie assigned to a new Keycloak group
    When the group is deleted in Keycloak
    Then the zaak and the taak still open, with the group's name
    And the zaak and the taak can be assigned to another group and behandelaar
""")
def test_deleted_group_leaves_its_zaak_and_taak_reassignable(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    zac_taken_zaak: Callable[[], JsonObject],
    zac_group: str,
    registry: ResourceRegistry,
) -> None:
    """ZAC shows a deleted group by its name and lets the zaak and taak move to another group."""
    zac_url = urls["zac"]
    group = make_role_group(podiumd_env, registry, "behandelaar")
    zaak, taak = _zaak_and_taak(zac, zac_url, zac_taken_zaak, group)

    _keycloak(podiumd_env).delete_group(_group_id(podiumd_env, group))
    zaak_groep, taak_groep = _groepen(zac, zac_url, zaak, taak)
    assert zaak_groep == taak_groep == {"id": group, "naam": group, "active": True}

    expect_status(toekennen(zac, zac_url, zaak, zac_group, ADMIN.username), HTTPStatus.OK)
    toekennen_taak(zac, zac_url, taak, zac_group, ADMIN.username)
    assert assignment(read_zaak(zac, zac_url, str(zaak["uuid"]))) == (zac_group, ADMIN.username)
    assert assignment(read_taak(zac, zac_url, str(taak["id"]))) == (zac_group, ADMIN.username)
