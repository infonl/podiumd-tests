"""ZAC's rights per application role, each through a test user that has only that role.

Bootstrap maps each user's realm role in PABC to one ZAC application role on the BPMN test zaaktype (step
zac-bpmn-process), so the rights do not depend on the estate's PABC dataset. The expected rights are ZAC 5.9.1's
OPA policies (src/main/resources/policies/*.rego); the ZAC tests skip below 5.9.1.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import BPMN_ZAAKTYPE
from podiumd_tests.bootstrap.names import ZAC_BASE_ROLES
from podiumd_tests.bootstrap.names import ZAC_FUNCTIONAL_ROLES
from podiumd_tests.bootstrap.steps import ZAC_ROLE_USERS
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.pabc import decide
from podiumd_tests.pabc import mapped_application_roles
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.results import TAG_PREFIX
from podiumd_tests.zac import POLICIES
from podiumd_tests.zac import can_open_zaak
from podiumd_tests.zac import is_zaak_listed
from podiumd_tests.zac import rights_of
from podiumd_tests.zac import wait_in_werkvoorraad

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "pabc", "keycloak")]

# The least base role that has each right, per policy read-out (overige-, werklijst- and notitie-rechten.rego).
POLICY = {
    "overigeRechten": {"startenZaak": "behandelaar", "beheren": "beheerder", "zoeken": "raadpleger"},
    "werklijstRechten": {
        "inbox": "coordinator",
        "ontkoppeldeDocumentenVerwijderen": "recordmanager",
        "inboxProductaanvragenVerwijderen": "recordmanager",
        "zakenTaken": "raadpleger",
        "zakenTakenVerdelen": "coordinator",
        "zakenTakenExporteren": "beheerder",
    },
    "notitieRechten": {"lezen": "raadpleger", "wijzigen": "behandelaar"},
}
# The same for the rechten of an open zaak (zaak-rechten.rego); heropenen has no open check.
ZAAK = {
    "lezen": "raadpleger",
    "wijzigen": "behandelaar",
    "behandelen": "behandelaar",
    "heropenen": "recordmanager",
    "bekijkenZaakdata": "beheerder",
}
# Calls the least role with the right may make and the role below it may not; none creates anything.
# No notitie or ontkoppeld document has this id; ZAC answers 204 for a missing one.
NO_ID = 999999999999
CHECKS = [
    pytest.param("DELETE", f"/rest/notities/{NO_ID}", None, "behandelaar", HTTPStatus.NO_CONTENT, id="notitie"),
    pytest.param(
        "PUT", "/rest/inboxdocumenten", {"page": 0, "maxResults": 1}, "coordinator", HTTPStatus.OK, id="inbox"
    ),
    pytest.param(
        "DELETE", f"/rest/ontkoppeldedocumenten/{NO_ID}", None, "recordmanager", HTTPStatus.NO_CONTENT, id="ontkoppeld"
    ),
    pytest.param("GET", "/rest/referentietabellen", None, "beheerder", HTTPStatus.OK, id="beheer"),
    pytest.param(
        "POST", "/rest/csv/export", {"page": 0, "rows": 1, "type": "ZAAK"}, "beheerder", HTTPStatus.OK, id="export"
    ),
]


def pabc_decision(http: requests.Session, urls: dict[str, str], api_key: str, role: str) -> JsonObject:
    """PABC's decision for one functional role alone."""
    return expect_status(decide(http, urls["pabc"], api_key, [role]), HTTPStatus.OK).json()


def skip_without_brp_zoeken(decision: JsonObject) -> None:
    """Skip when PABC gives the brp_zoeken user no role: podiumd chart 4.9's PABC dataset lacks brp_zoeken."""
    if not mapped_application_roles(decision, BPMN_ZAAKTYPE):
        pytest.skip("PABC has no application role brp_zoeken: add it to PABC's dataset (podiumd chart 4.10 has it)")


@pytest.mark.source(
    "podiumd-tests",
    "The BPMN and role tests must not depend on the estate's PABC dataset: bootstrap maps its own roles in its own"
    " domain.",
)
@pytest.mark.scenario("""
    Given a realm role of podiumd-tests, which bootstrap gives the test admin or a test user with one ZAC role
    When ZAC asks PABC for the rights of that role alone
    Then PABC gives the role's application roles on the BPMN test zaaktype
    And on no zaaktype of the estate
""")
@pytest.mark.parametrize("role", ZAC_FUNCTIONAL_ROLES)
def test_rights_come_from_podiumd_tests_own_pabc_roles(
    http: requests.Session, urls: dict[str, str], pabc_api_key: str, need_bootstrap: Callable[..., None], role: str
) -> None:
    """PABC's decision for the role alone covers the BPMN test zaaktype, with the role's application roles, only."""
    need_bootstrap("zac-bpmn-process")
    decision = pabc_decision(http, urls, pabc_api_key, role)
    if ZAC_FUNCTIONAL_ROLES[role] == ("brp_zoeken",):
        skip_without_brp_zoeken(decision)
    assert mapped_application_roles(decision, BPMN_ZAAKTYPE) == set(ZAC_FUNCTIONAL_ROLES[role])
    covered = {str(section(r, "entityType").get("id")) for r in entries(decision.get("results")) if r.get("entityType")}
    assert BPMN_ZAAKTYPE in covered
    # Tests of the run add their own zaaktypen (TAG_PREFIX) to the domain at the same time.
    assert [entity for entity in covered if not entity.startswith(TAG_PREFIX)] == [], "a zaaktype of the estate"


@pytest.mark.source(POLICIES, "Each base role has the rights of the roles below it and the rights of its own.")
@pytest.mark.scenario("""
    Given a test user with only one ZAC base role on the BPMN test zaaktype
    And an open zaak of that zaaktype
    When the user reads ZAC's policy rights and the zaak's rechten
    Then the user has each right ZAC gives this role or a lower role, and no other right
""")
@pytest.mark.parametrize("role", ZAC_BASE_ROLES)
def test_rights_follow_the_role(
    zac_as: Callable[[str], requests.Session], urls: dict[str, str], bpmn_zaak: JsonObject, role: str
) -> None:
    """The user's policy read-outs and the open zaak's rechten match ZAC 5.9.1's least role per right."""
    http = zac_as(role)
    actual: dict[str, object] = {}
    expected: dict[str, bool] = {}
    for endpoint, rights in POLICY.items():
        body = expect_status(http.get(f"{urls['zac']}/rest/policy/{endpoint}"), HTTPStatus.OK).json()
        actual |= {f"{endpoint}.{right}": body.get(right) for right in rights}
        expected |= {f"{endpoint}.{right}": has for right, has in rights_of(role, rights).items()}
    zaak = expect_status(http.get(f"{urls['zac']}/rest/zaken/zaak/{bpmn_zaak['uuid']}"), HTTPStatus.OK).json()
    actual |= {f"zaak.{right}": section(zaak, "rechten").get(right) for right in ZAAK}
    expected |= {f"zaak.{right}": has for right, has in rights_of(role, ZAAK).items()}
    assert actual == expected


@pytest.mark.source(POLICIES, "ZAC's REST services refuse a call the user's role has no right to, with 403.")
@pytest.mark.scenario("""
    Given a test user with the least ZAC base role for a call and one with the role below it
    When both make the call
    Then ZAC refuses the lower role with 403
    And accepts the call of the least role
""")
@pytest.mark.parametrize(("method", "path", "body", "least", "accepted"), CHECKS)
def test_zac_refuses_a_call_below_its_least_role(
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    method: str,
    path: str,
    body: JsonObject | None,
    least: str,
    accepted: HTTPStatus,
) -> None:
    """The role just below `least` gets 403 for the call; `least` gets `accepted`."""
    below = ZAC_BASE_ROLES[ZAC_BASE_ROLES.index(least) - 1]
    refused = zac_as(below).request(method, urls["zac"] + path, json=body)
    assert refused.status_code == HTTPStatus.FORBIDDEN, f"{below}: {describe(refused)}"
    expect_status(zac_as(least).request(method, urls["zac"] + path, json=body), accepted)


@pytest.mark.source(POLICIES, "A role on one zaaktype gives no rights on the zaken of another zaaktype.")
@pytest.mark.scenario("""
    Given a test user with ZAC base role behandelaar on the BPMN test zaaktype only
    And a zaak of the estate's zaaktype for productaanvragen
    When the user opens that zaak
    Then ZAC refuses access
""")
def test_role_gives_no_access_to_zaken_of_other_zaaktypen(
    zac_as: Callable[[str], requests.Session], urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """The behandelaar of the BPMN test zaaktype gets 403 for a zaak of the estate's zaaktype."""
    zaak = zac_zaak()
    assert not can_open_zaak(zac_as("behandelaar"), urls["zac"], zaak)


@pytest.mark.source(POLICIES, "ZAC's search lists only zaken of zaaktypen the user holds a base role for (PR #7221).")
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype and a zaak of the estate's zaaktype in ZAC's werkvoorraad
    And a test user with ZAC base role raadpleger on the BPMN test zaaktype only
    When the user searches for each zaak
    Then ZAC lists the zaak of the BPMN test zaaktype
    And not the zaak of the estate's zaaktype
""")
def test_search_lists_only_zaken_of_zaaktypen_with_a_role(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_zaak: Callable[..., JsonObject],
) -> None:
    """Once both zaken are indexed, the raadpleger's search finds the BPMN zaak and not the estate's zaak."""
    other = zac_zaak()
    for zaak in (bpmn_zaak, other):
        wait_in_werkvoorraad(zac, urls["zac"], zaak)
    raadpleger = zac_as("raadpleger")
    assert is_zaak_listed(raadpleger, urls["zac"], bpmn_zaak)
    assert not is_zaak_listed(raadpleger, urls["zac"], other)


@pytest.mark.source(POLICIES, "A user without a base role cannot use ZAC, whatever plus roles it has (PR #7232).")
@pytest.mark.scenario("""
    Given a test user with only the plus role brp_zoeken on the BPMN test zaaktype
    When the user logs in to ZAC and asks who is logged in
    Then ZAC refuses the request
""")
def test_plus_role_alone_gives_no_access(
    zac_as: Callable[[str], requests.Session], http: requests.Session, urls: dict[str, str], pabc_api_key: str
) -> None:
    """The user with only brp_zoeken gets 403 from ZAC's REST API after logging in."""
    user = ZAC_ROLE_USERS["brp_zoeken"]
    skip_without_brp_zoeken(pabc_decision(http, urls, pabc_api_key, user.realm_roles[0]))
    refused = zac_as("brp_zoeken").get(f"{urls['zac']}/rest/identity/loggedInUser")
    assert refused.status_code == HTTPStatus.FORBIDDEN, describe(refused)
