"""ZAC's access rules (its OPA policies) on closed zaken, documents, beheer, verdelen and related zaken.

Every ZAC REST call asks ZAC's OPA sidecar for the user's rights; a call that succeeds shows that OPA allows. The
tests per role log in as bootstrap's test user with only that ZAC application role on the BPMN test zaaktype
(fixture zac_as); the expected rights are ZAC 5.9.1's policies.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import INTAKE
from podiumd_tests.bootstrap.names import ZAC_BASE_ROLES
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import GERELATEERD
from podiumd_tests.zac import HEROPEND
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import POLICIES
from podiumd_tests.zac import afsluiten
from podiumd_tests.zac import assignment
from podiumd_tests.zac import can_open_zaak
from podiumd_tests.zac import heropenen
from podiumd_tests.zac import koppel
from podiumd_tests.zac import ontkoppel
from podiumd_tests.zac import open_task
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import rights_of
from podiumd_tests.zac import verdelen
from podiumd_tests.zac import verdelen_taken
from podiumd_tests.zac import vrijgeven
from podiumd_tests.zac import vrijgeven_taken
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac import zac_session
from podiumd_tests.zac_documents import delete_document
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import lock_document
from podiumd_tests.zac_documents import nieuwe_versie
from podiumd_tests.zac_documents import unlock_document
from podiumd_tests.zac_documents import uploaded_document

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

# The least base role with each right on a closed zaak (zaak-rechten.rego); None: no base role.
CLOSED_ZAAK = {
    "lezen": "raadpleger",
    "behandelen": "behandelaar",
    "wijzigen": "recordmanager",
    "toekennen": "recordmanager",
    "heropenen": "recordmanager",
    "toevoegenInitiatorPersoon": "recordmanager",
    "toevoegenBetrokkeneBedrijf": "recordmanager",
    "verwijderenBetrokkene": "recordmanager",
    "toevoegenBagObject": "recordmanager",
    "wijzigenLocatie": "recordmanager",
    "bekijkenZaakdata": "beheerder",
    "wijzigenDoorlooptijd": None,
    "creerenDocument": None,
    "versturenEmail": None,
    "versturenOntvangstbevestiging": None,
}
# ZAC's beheer endpoints that only read; each checks the right beheren (overige-rechten.rego).
BEHEER = (
    "/rest/admin/util",
    "/rest/beheer/mailtemplates",
    "/rest/zaakafhandelparameters",
    "/rest/bpmn-process-definitions",
)


@pytest.mark.source(
    "podiumd-tests",
    "ZAC's OPA policies must refuse a user without ZAC roles; helm-charts #633 updates OPA.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC that the test admin can open
    And a klantcontactmedewerker without ZAC roles is logged in to ZAC
    When the klantcontactmedewerker opens the same zaak
    Then ZAC refuses access
""")
def test_user_without_zac_roles_cannot_read_a_zaak(
    zac: requests.Session,
    podiumd_env: Environment,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    need_bootstrap: Callable[..., None],
) -> None:
    """The admin reads the zaak; the KCC user, logged in to ZAC as well, gets 403 for the same zaak."""
    zaak = zac_zaak()
    assert can_open_zaak(zac, urls["zac"], zaak)
    need_bootstrap(KCC.name)
    kcc = zac_session(podiumd_env, KCC.username, podiumd_env.credentials.get(KCC.store_key))
    assert not can_open_zaak(kcc, urls["zac"], zaak)


@pytest.fixture(name="closed_bpmn_zaak")
def fixture_closed_bpmn_zaak(zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject) -> JsonObject:
    """The BPMN test zaak, afgehandeld by the test admin."""
    return expect_status(afsluiten(zac, urls["zac"], bpmn_zaak), HTTPStatus.OK).json()


@pytest.mark.requires("pabc")
@pytest.mark.source(POLICIES, "On a closed zaak only a recordmanager or beheerder may change it, never its dates.")
@pytest.mark.scenario("""
    Given an afgehandelde zaak of the BPMN test zaaktype
    When each test user with one ZAC base role reads the zaak's rechten
    Then a behandelaar and coordinator may no longer change the zaak, its betrokkenen or documents
    And a recordmanager and beheerder may change it and heropenen it, but not its dates
    And no role may send mail from it or add a document to it
""")
def test_closed_zaak_rights_follow_the_role(
    zac_as: Callable[[str], requests.Session], urls: dict[str, str], closed_bpmn_zaak: JsonObject
) -> None:
    """The closed zaak's rechten per base role match ZAC 5.9.1's least role per right on a closed zaak."""
    actual = {}
    for role in ZAC_BASE_ROLES:
        rechten = section(read_zaak(zac_as(role), urls["zac"], str(closed_bpmn_zaak["uuid"])), "rechten")
        actual[role] = {right: rechten.get(right) for right in CLOSED_ZAAK}
    assert actual == {role: rights_of(role, CLOSED_ZAAK) for role in ZAC_BASE_ROLES}


@pytest.mark.requires("pabc")
@pytest.mark.source(POLICIES, "A closed zaak is changed and heropend only by a recordmanager or beheerder.")
@pytest.mark.scenario("""
    Given an afgehandelde zaak of the BPMN test zaaktype
    When a behandelaar or a coordinator changes its omschrijving
    Then ZAC refuses it
    When a recordmanager changes its omschrijving
    Then the zaak has the new omschrijving
    But ZAC refuses the recordmanager a new uiterlijke einddatum afdoening
    And ZAC refuses the behandelaar to heropenen the zaak
""")
def test_closed_zaak_is_changed_only_by_a_recordmanager(
    zac_as: Callable[[str], requests.Session], urls: dict[str, str], closed_bpmn_zaak: JsonObject
) -> None:
    """Behandelaar and coordinator get 403 for an edit and heropenen; the recordmanager edits, but gets 403 for a date."""
    zaak, zac_url = closed_bpmn_zaak, urls["zac"]
    omschrijving = f"{zaak['omschrijving']}-gewijzigd"
    for role in ("behandelaar", "coordinator"):
        refused = wijzig_zaak(zac_as(role), zac_url, zaak, omschrijving=omschrijving)
        assert refused.status_code == HTTPStatus.FORBIDDEN, f"{role}: {describe(refused)}"
    recordmanager = zac_as("recordmanager")
    expect_status(wijzig_zaak(recordmanager, zac_url, zaak, omschrijving=omschrijving), HTTPStatus.OK)
    assert read_zaak(recordmanager, zac_url, str(zaak["uuid"]))["omschrijving"] == omschrijving
    later = (date.fromisoformat(str(zaak["uiterlijkeEinddatumAfdoening"])) + timedelta(days=1)).isoformat()
    refused = wijzig_zaak(recordmanager, zac_url, zaak, uiterlijkeEinddatumAfdoening=later)
    assert refused.status_code == HTTPStatus.FORBIDDEN, describe(refused)
    refused = heropenen(zac_as("behandelaar"), zac_url, zaak)
    assert refused.status_code == HTTPStatus.FORBIDDEN, describe(refused)


@pytest.mark.requires("pabc")
@pytest.mark.source(POLICIES, "A recordmanager may heropenen a closed zaak; ZAC gives it the status Heropend.")
@pytest.mark.scenario("""
    Given an afgehandelde zaak of the BPMN test zaaktype
    When a recordmanager heropent it with a reden
    Then ZAC shows the zaak open with status Heropend
    And Open Zaak has the zaak without einddatum and with status Heropend
""")
def test_recordmanager_heropent_a_closed_zaak(
    zac_as: Callable[[str], requests.Session], urls: dict[str, str], openzaak: ApiClient, closed_bpmn_zaak: JsonObject
) -> None:
    """The recordmanager's heropenen answers 200; ZAC and Open Zaak have the zaak open with statustype Heropend."""
    response = heropenen(zac_as("recordmanager"), urls["zac"], closed_bpmn_zaak)
    reopened = expect_status(response, HTTPStatus.OK).json()
    assert (section(reopened, "status").get("naam"), reopened["isOpen"]) == (HEROPEND, True)
    in_open_zaak = openzaak.get(f"{urls['openzaak']}/{ZAKEN}/zaken/{closed_bpmn_zaak['uuid']}")
    statustype = openzaak.get(str(openzaak.get(str(in_open_zaak["status"]))["statustype"]))
    assert (in_open_zaak["einddatum"], statustype["omschrijving"]) == (None, HEROPEND)


@pytest.mark.requires("pabc")
@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
)
@pytest.mark.xfail(
    strict=True,
    reason="[zac-17] ZAC 5.9.1 heropent a closed zaak without a reden (RestZaakHeropenenGegevens.reden is optional); "
    "not yet reported upstream",
)
@pytest.mark.scenario("""
    Given an afgehandelde zaak of the BPMN test zaaktype
    When a recordmanager heropent it without a reden
    Then ZAC refuses it
    And the zaak stays closed
""")
def test_heropenen_needs_a_reden(
    zac: requests.Session, zac_as: Callable[[str], requests.Session], urls: dict[str, str], closed_bpmn_zaak: JsonObject
) -> None:
    """Heropenen with an empty body is refused with 400 and the zaak stays closed."""
    zac_url = urls["zac"]
    response = zac_as("recordmanager").patch(f"{zac_url}/rest/zaken/zaak/{closed_bpmn_zaak['uuid']}/heropenen", json={})
    assert response.status_code == HTTPStatus.BAD_REQUEST, describe(response)
    assert read_zaak(zac, zac_url, str(closed_bpmn_zaak["uuid"]))["isOpen"] is False


def _ondertekend(
    zac: requests.Session, zac_url: str, zaak: JsonObject, document: JsonObject, _: ResourceRegistry
) -> None:
    url = document_url(zac_url, document)
    expect_status(zac.post(f"{url}/onderteken", params={"zaak": str(zaak["uuid"])}), HTTPStatus.OK)


def _afgehandeld(
    zac: requests.Session, zac_url: str, zaak: JsonObject, _document: JsonObject, _registry: ResourceRegistry
) -> None:
    expect_status(afsluiten(zac, zac_url, zaak), HTTPStatus.OK)


def _new_version(http: requests.Session, zac_url: str, zaak: JsonObject, document: JsonObject) -> requests.Response:
    return nieuwe_versie(http, zac_url, zaak, document, {"beschrijving": "podiumd-tests"})


# Per state of a document: how the test admin brings it there, the least base role with each right
# (document-rechten.rego; None: no base role) and a call the recordmanager may make and the behandelaar may not.
DOCUMENT_STATES = [
    pytest.param(
        lock_document,
        {
            "lezen": "raadpleger",
            "vergrendelen": "behandelaar",
            "wijzigen": "recordmanager",
            "ontgrendelen": "recordmanager",
            "toevoegenNieuweVersie": "recordmanager",
            "verwijderen": None,
            "ondertekenen": None,
            "converteren": None,
        },
        unlock_document,
        id="vergrendeld-door-een-ander",
    ),
    pytest.param(
        _ondertekend,
        {
            "lezen": "raadpleger",
            "vergrendelen": "behandelaar",
            "ondertekenen": "behandelaar",
            "converteren": "behandelaar",
            "wijzigen": "recordmanager",
            "ontgrendelen": "recordmanager",
            "toevoegenNieuweVersie": "recordmanager",
            "verwijderen": "recordmanager",
        },
        _new_version,
        id="ondertekend",
    ),
    pytest.param(
        _afgehandeld,
        {
            "lezen": "raadpleger",
            "wijzigen": "recordmanager",
            "ontgrendelen": "recordmanager",
            "toevoegenNieuweVersie": "recordmanager",
            "verwijderen": "recordmanager",
            "vergrendelen": None,
            "ondertekenen": None,
            "converteren": None,
        },
        delete_document,
        id="zaak-afgehandeld",
    ),
]


@pytest.mark.requires("pabc")
@pytest.mark.source(POLICIES, "A recordmanager may change locked, definitief and closed-zaak documents; others not.")
@pytest.mark.scenario("""
    Given a PDF in bewerking on a zaak of the BPMN test zaaktype
    And the test admin locked it, signed it, or afgehandeld the zaak
    When each test user with one ZAC base role reads the document's rechten
    Then a behandelaar and coordinator may not change it, add a version or delete it
    And a recordmanager and beheerder may
    And ZAC refuses the behandelaar's unlock, new version or delete, and accepts the recordmanager's
""")
@pytest.mark.parametrize(("prepare", "least_roles", "call"), DOCUMENT_STATES)
def test_document_rights_follow_the_role_and_the_state(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    registry: ResourceRegistry,
    prepare: Callable[..., None],
    least_roles: dict[str, str | None],
    call: Callable[..., requests.Response],
) -> None:
    """The document's rechten per base role match ZAC 5.9.1; the state's call is 403 for a behandelaar only."""
    zac_url = urls["zac"]
    document = uploaded_document(zac, zac_url, bpmn_zaak, registry, suffix="pdf", status="in_bewerking")
    prepare(zac, zac_url, bpmn_zaak, document, registry)
    url, of_zaak = document_url(zac_url, document), {"zaak": str(bpmn_zaak["uuid"])}
    actual = {}
    for role in ZAC_BASE_ROLES:
        rechten = section(expect_status(zac_as(role).get(url, params=of_zaak), HTTPStatus.OK).json(), "rechten")
        actual[role] = {right: rechten.get(right) for right in least_roles}
    assert actual == {role: rights_of(role, least_roles) for role in ZAC_BASE_ROLES}
    refused = call(zac_as("behandelaar"), zac_url, bpmn_zaak, document)
    assert refused.status_code == HTTPStatus.FORBIDDEN, describe(refused)
    expect_status(call(zac_as("recordmanager"), zac_url, bpmn_zaak, document), HTTPStatus.OK, HTTPStatus.NO_CONTENT)


@pytest.mark.requires("pabc")
@pytest.mark.source(POLICIES, "ZAC's beheer pages and /rest/admin are for the beheerder only.")
@pytest.mark.scenario("""
    Given a test user with only one ZAC base role
    When the user opens ZAC's beheer: admin util, mailtemplates, zaakafhandelparameters and BPMN processes
    Then ZAC refuses every one of them, unless the user is beheerder
""")
@pytest.mark.parametrize("role", ZAC_BASE_ROLES)
def test_beheer_is_refused_to_every_role_but_beheerder(
    zac_as: Callable[[str], requests.Session], urls: dict[str, str], role: str
) -> None:
    """Each read-only beheer endpoint answers 200 to the beheerder and 403 to every other base role."""
    http = zac_as(role)
    actual = {path: http.get(urls["zac"] + path).status_code for path in BEHEER}
    wanted = HTTPStatus.OK if role == "beheerder" else HTTPStatus.FORBIDDEN
    assert actual == dict.fromkeys(BEHEER, wanted)


@pytest.mark.requires("pabc")
@pytest.mark.source(POLICIES, "Only a coordinator or a role above it may verdelen and vrijgeven from the werkvoorraad.")
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype in a group, without behandelaar
    When a behandelaar verdeelt or vrijgeeft it from the werkvoorraad
    Then ZAC refuses both
    When a coordinator verdeelt it to the group and the test admin
    Then the zaak has that group and behandelaar
    When the coordinator vrijgeeft it
    Then the zaak keeps the group but has no behandelaar
""")
def test_only_a_coordinator_verdeelt_and_vrijgeeft(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
) -> None:
    """Verdelen and vrijgeven answer 403 to the behandelaar; the coordinator's change the zaak's behandelaar."""
    zac_url, uuids = urls["zac"], [str(bpmn_zaak["uuid"])]
    behandelaar = zac_as("behandelaar")
    for refused in (
        verdelen(behandelaar, zac_url, uuids, zac_group, ADMIN.username),
        vrijgeven(behandelaar, zac_url, uuids),
    ):
        assert refused.status_code == HTTPStatus.FORBIDDEN, describe(refused)

    def is_(wanted: tuple[object, object]) -> bool:
        return assignment(read_zaak(zac, zac_url, uuids[0])) == wanted

    coordinator = zac_as("coordinator")
    expect_status(verdelen(coordinator, zac_url, uuids, zac_group, ADMIN.username), HTTPStatus.NO_CONTENT)
    wait_until(lambda: is_((zac_group, ADMIN.username)), timeout=LIST_TIMEOUT, description="zaak verdeeld")
    expect_status(vrijgeven(coordinator, zac_url, uuids), HTTPStatus.NO_CONTENT)
    wait_until(lambda: is_((zac_group, None)), timeout=LIST_TIMEOUT, description="zaak vrijgegeven")


@pytest.mark.requires("pabc")
@pytest.mark.source(POLICIES, "Only a coordinator or a role above it may verdelen and vrijgeven taken from the list.")
@pytest.mark.scenario("""
    Given the intake taak of a zaak of the BPMN test zaaktype
    When a behandelaar verdeelt or vrijgeeft it from the takenlijst
    Then ZAC refuses both
""")
def test_only_a_coordinator_verdeelt_and_vrijgeeft_taken(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
) -> None:
    """Verdelen and vrijgeven of taken answer 403 to the behandelaar."""
    taken = [open_task(zac, urls["zac"], str(bpmn_zaak["uuid"]), INTAKE)]
    behandelaar = zac_as("behandelaar")
    for refused in (
        verdelen_taken(behandelaar, urls["zac"], taken, zac_group, ADMIN.username),
        vrijgeven_taken(behandelaar, urls["zac"], taken),
    ):
        assert refused.status_code == HTTPStatus.FORBIDDEN, describe(refused)


@pytest.mark.requires("pabc")
@pytest.mark.source(POLICIES, "Relating zaken needs the right to read the other zaak (ZaakLinkData.canBeRelatedTo).")
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype, which the test admin related to a zaak of the estate's zaaktype
    And a behandelaar with a role on the BPMN test zaaktype only
    When the behandelaar opens the zaak
    Then the related zaak shows only its zaaknummer, and cannot be unlinked
    And ZAC refuses the behandelaar's unlinking of it, and relating another zaak of the estate's zaaktype
""")
def test_relating_zaken_needs_read_rights_on_the_other_zaak(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_zaak: Callable[..., JsonObject],
) -> None:
    """Without lezen on the other zaak: no zaaktype shown, ontkoppelen false, and koppel and ontkoppel get 403."""
    zac_url = urls["zac"]
    other, third = zac_zaak(), zac_zaak()
    expect_status(koppel(zac, zac_url, bpmn_zaak, other, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    behandelaar = zac_as("behandelaar")
    shown = entries(read_zaak(behandelaar, zac_url, str(bpmn_zaak["uuid"])).get("gerelateerdeZaken"))
    related = [item for item in shown if item.get("identificatie") == other["identificatie"]]
    assert [(item.get("zaaktypeOmschrijving"), item.get("ontkoppelen")) for item in related] == [(None, False)], shown
    answers = {
        "ontkoppelen": ontkoppel(behandelaar, zac_url, bpmn_zaak, other, GERELATEERD, "podiumd-tests"),
        "koppelen": koppel(behandelaar, zac_url, bpmn_zaak, third, GERELATEERD),
    }
    assert {call: answer.status_code for call, answer in answers.items()} == dict.fromkeys(
        answers, HTTPStatus.FORBIDDEN
    ), {call: describe(answer) for call, answer in answers.items()}
