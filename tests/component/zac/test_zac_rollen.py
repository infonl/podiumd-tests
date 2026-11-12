"""ZAC's rights per application role, each through a test user that has only that role.

Bootstrap maps each user's realm role in PABC to one ZAC application role on the BPMN test zaaktype (step
zac-bpmn-process), so the rights do not depend on the estate's PABC dataset. The expected rights are ZAC 5.9.1's
OPA policies (src/main/resources/policies/*.rego); the ZAC tests skip below 5.9.1.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.bootstrap.bpmn import INTAKE
from podiumd_tests.bootstrap.names import BPMN_BESLUITTYPE
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
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_other_domain_group
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.zac import GERELATEERD
from podiumd_tests.zac import POLICIES
from podiumd_tests.zac import besluittypen
from podiumd_tests.zac import can_open_zaak
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import is_zaak_listed
from podiumd_tests.zac import koppel_zoekresultaat
from podiumd_tests.zac import open_task
from podiumd_tests.zac import read_taak
from podiumd_tests.zac import recorded_besluit
from podiumd_tests.zac import rights_of
from podiumd_tests.zac import vastleggen_besluit
from podiumd_tests.zac import wait_in_werkvoorraad
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac import zaak_body
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

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
# The same for the rechten of an open zaak (zaak-rechten.rego); heropenen has no open check, brondatumZetten needs a
# closed zaak.
BEHANDELAAR_RECHTEN = (
    "wijzigen",
    "toekennen",
    "behandelen",
    "afbreken",
    "wijzigenDoorlooptijd",
    "toevoegenBagObject",
    "toevoegenBetrokkeneBedrijf",
    "toevoegenBetrokkenePersoon",
    "toevoegenInitiatorBedrijf",
    "toevoegenInitiatorPersoon",
    "versturenOntvangstbevestiging",
    "verwijderenBetrokkene",
    "verwijderenInitiator",
    "creerenDocument",
    "versturenEmail",
    "wijzigenLocatie",
)
ZAAK: dict[str, str | None] = {
    "lezen": "raadpleger",
    **dict.fromkeys(BEHANDELAAR_RECHTEN, "behandelaar"),
    "heropenen": "recordmanager",
    "bekijkenZaakdata": "beheerder",
    "brondatumZetten": None,
}
# The same for the rechten of an open taak (taak-rechten.rego).
TAAK = {
    "lezen": "raadpleger",
    "wijzigen": "behandelaar",
    "toekennen": "behandelaar",
    "toevoegenDocument": "behandelaar",
}
# vastleggen_besluit in zaak-rechten.rego; ZAC gives it in no read-out.
BESLUIT = {"vastleggen": "behandelaar"}
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


@pytest.mark.source(
    POLICIES, "A taak's rechten follow the base role: any base role reads it, a behandelaar changes it."
)
@pytest.mark.scenario("""
    Given a test user with only one ZAC base role on the BPMN test zaaktype
    And an open zaak of that zaaktype with its open taak Intake
    When the user lists the zaak's taken and reads the taak
    Then the user has each right on the taak ZAC gives this role or a lower role, and no other right
""")
@pytest.mark.parametrize("role", ZAC_BASE_ROLES)
def test_taak_rights_follow_the_role(
    zac_as: Callable[[str], requests.Session], urls: dict[str, str], bpmn_zaak: JsonObject, role: str
) -> None:
    """The user finds the Intake taak in the zaak's taken; its rechten match ZAC 5.9.1's least role per right."""
    http = zac_as(role)
    taak = open_task(http, urls["zac"], str(bpmn_zaak["uuid"]), INTAKE)
    rechten = section(read_taak(http, urls["zac"], str(taak["id"])), "rechten")
    assert {right: rechten.get(right) for right in TAAK} == rights_of(role, TAAK)


@pytest.mark.source(POLICIES, "Only a behandelaar or a higher base role records a besluit on a zaak.")
@pytest.mark.scenario("""
    Given a test user with only one ZAC base role on the BPMN test zaaktype, which has a besluittype
    And an open zaak of that zaaktype
    When the user records a besluit on the zaak
    Then ZAC records it for a behandelaar or a higher role
    And refuses it for a raadpleger
""")
@pytest.mark.parametrize("role", ZAC_BASE_ROLES)
def test_besluit_rights_follow_the_role(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    bpmn_zaak: JsonObject,
    role: str,
) -> None:
    """A besluit is recorded by a behandelaar and higher; a raadpleger gets 403."""
    besluittype = next(item for item in besluittypen(zac, urls["zac"], bpmn_zaak) if item["naam"] == BPMN_BESLUITTYPE)
    http = zac_as(role)
    if rights_of(role, BESLUIT)["vastleggen"]:
        recorded_besluit(http, urls["zac"], openzaak, registry, bpmn_zaak, besluittype)
        return
    refused = vastleggen_besluit(http, urls["zac"], bpmn_zaak, besluittype, toelichting="podiumd-tests")
    assert refused.status_code == HTTPStatus.FORBIDDEN, describe(refused)


@pytest.mark.source(POLICIES, "A raadpleger reads zaken but cannot create a zaak or change one.")
@pytest.mark.scenario("""
    Given a test user with only ZAC base role raadpleger on the BPMN test zaaktype
    And an open zaak of that zaaktype
    When the user creates a zaak of that zaaktype, or changes the zaak's streefdatum and fatale datum
    Then ZAC refuses each with 403
""")
def test_raadpleger_cannot_create_or_change_a_zaak(
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_parameters: JsonObject,
    bpmn_zaak: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """ZAC answers 403 to the raadpleger's new zaak and to its date change."""
    raadpleger = zac_as("raadpleger")
    body = zaak_body(bpmn_parameters, omschrijving=registry.tagged("raadpleger"))
    later = (date.today() + timedelta(days=30)).isoformat()  # noqa: DTZ011  # ZAC's local date
    answers = {
        "new zaak": raadpleger.post(f"{urls['zac']}/rest/zaken/zaak", json=body),
        "dates": wijzig_zaak(
            raadpleger, urls["zac"], bpmn_zaak, einddatumGepland=later, uiterlijkeEinddatumAfdoening=later
        ),
    }
    assert {call: answer.status_code for call, answer in answers.items()} == dict.fromkeys(
        answers, HTTPStatus.FORBIDDEN
    ), {call: describe(answer) for call, answer in answers.items()}


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
    for flags in ({}, {"alleenOpenstaandeZaken": True}):
        assert is_zaak_listed(raadpleger, urls["zac"], bpmn_zaak, **flags)
        assert not is_zaak_listed(raadpleger, urls["zac"], other, **flags)


@pytest.mark.source(POLICIES, "ZAC's search for zaken to link lists only zaken of zaaktypen the user holds a role for.")
@pytest.mark.scenario("""
    Given two zaken of the BPMN test zaaktype and a zaak of the estate's zaaktype in ZAC's werkvoorraad
    And a test user with ZAC base role behandelaar on the BPMN test zaaktype only
    When the user searches for each other zaak to link to the first zaak
    Then ZAC finds the zaak of the BPMN test zaaktype
    And not the zaak of the estate's zaaktype
""")
def test_koppel_search_lists_only_zaken_of_zaaktypen_with_a_role(  # three zaken and two users
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    bpmn_parameters: JsonObject,
    bpmn_zaak: JsonObject,
    zac_zaak: Callable[..., JsonObject],
) -> None:
    """The behandelaar's koppel search from a BPMN zaak finds the other BPMN zaak and not the estate's zaak."""
    zac_url = urls["zac"]
    tweede = create_zaak(zac, zac_url, bpmn_parameters, omschrijving=registry.tagged("bpmn"))
    clean_up_zaak(zac, zac_url, openzaak, registry, tweede)
    other = zac_zaak()
    for zaak in (tweede, other):
        wait_in_werkvoorraad(zac, zac_url, zaak)
    behandelaar = zac_as("behandelaar")
    assert koppel_zoekresultaat(behandelaar, zac_url, bpmn_zaak, tweede, GERELATEERD) is not None
    assert koppel_zoekresultaat(behandelaar, zac_url, bpmn_zaak, other, GERELATEERD) is None


@pytest.mark.source(
    POLICIES, "ZAC reads the user's zaaktypen from PABC at login: its search follows a lost role at once."
)
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype in ZAC's werkvoorraad
    And a user who is raadpleger on that zaaktype and on a zaaktype of another domain
    When the user loses the role on the BPMN test zaaktype and logs in again
    Then ZAC's search and werkvoorraad no longer list the zaak, without a reindex
""")
def test_search_follows_a_lost_role_without_a_reindex(
    zac: requests.Session,
    podiumd_env: Environment,
    urls: dict[str, str],
    registry: ResourceRegistry,
    bpmn_zaak: JsonObject,
) -> None:
    """Listed while the user is in the BPMN zaaktype's role group; after the group is gone, not listed."""
    zac_url = urls["zac"]
    wait_in_werkvoorraad(zac, zac_url, bpmn_zaak)
    group = make_role_group(podiumd_env, registry, "raadpleger")
    other = make_other_domain_group(podiumd_env, registry, "raadpleger")
    username, password = make_group_member(podiumd_env, registry, group, other)
    before = zac_session(podiumd_env, username, password)
    assert is_zaak_listed(before, zac_url, bpmn_zaak, alleenOpenstaandeZaken=True)

    for_environment(podiumd_env).delete_group_named(group)
    after = zac_session(podiumd_env, username, password)
    assert not is_zaak_listed(after, zac_url, bpmn_zaak)
    assert not is_zaak_listed(after, zac_url, bpmn_zaak, alleenOpenstaandeZaken=True)


@pytest.mark.source(POLICIES, "A plus role gives no rights on a zaaktype the user holds no base role for.")
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype in ZAC's werkvoorraad
    And a user who is raadpleger on a zaaktype of another domain
    And has only the plus role brp_zoeken on the BPMN test zaaktype
    When the user searches for the zaak
    Then ZAC's search and werkvoorraad do not list it
""")
def test_plus_role_in_another_domain_lists_no_zaken(  # the zaak, PABC and Keycloak
    zac: requests.Session,
    http: requests.Session,
    podiumd_env: Environment,
    urls: dict[str, str],
    pabc_api_key: str,
    registry: ResourceRegistry,
    bpmn_zaak: JsonObject,
) -> None:
    """The user logs in on its base role elsewhere; its search does not list the BPMN zaak."""
    skip_without_brp_zoeken(pabc_decision(http, urls, pabc_api_key, ZAC_ROLE_USERS["brp_zoeken"].realm_roles[0]))
    zac_url = urls["zac"]
    wait_in_werkvoorraad(zac, zac_url, bpmn_zaak)
    groups = (
        make_role_group(podiumd_env, registry, "brp-zoeken"),
        make_other_domain_group(podiumd_env, registry, "raadpleger"),
    )
    user = zac_session(podiumd_env, *make_group_member(podiumd_env, registry, *groups))
    assert not is_zaak_listed(user, zac_url, bpmn_zaak)
    assert not is_zaak_listed(user, zac_url, bpmn_zaak, alleenOpenstaandeZaken=True)


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
