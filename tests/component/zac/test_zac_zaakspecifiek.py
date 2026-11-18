"""ZAC's zaakspecifieke autorisatie: a behandelaar marks a zaak so only its authorised medewerkers reach it.

On a throwaway zaaktype with the eigenschap and roltype ZAC requires, in a new group with two new behandelaars.
The application role zaakspecifiek_geautoriseerd is not in PodiumD's PABC dataset, so its holders are not tested.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import NamedTuple

import pytest

from podiumd_tests import zac_taken
from podiumd_tests.bootstrap.bpmn import HARDCODED
from podiumd_tests.bootstrap.bpmn import HARDCODED_TO
from podiumd_tests.bootstrap.bpmn import PROCESS_KEY
from podiumd_tests.bootstrap.bpmn import TOEWIJZING
from podiumd_tests.bootstrap.bpmn import complete_intake
from podiumd_tests.json_data import section
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.zac_zaaktype import ZAAKSPECIFIEK_TYPES
from podiumd_tests.seed.zac_zaaktype import email_informatieobjecttype
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import is_older_than
from podiumd_tests.workloads import skip_older_than
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import assignment
from podiumd_tests.zac import can_open_zaak
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import verdelen
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac import zaak_historie
from podiumd_tests.zac import zac_session
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_search import document_zoekresultaat
from podiumd_tests.zac_search import is_taak_listed
from podiumd_tests.zac_search import is_zaak_listed
from podiumd_tests.zac_search import taak_zoekresultaat
from podiumd_tests.zac_search import zaak_zoekresultaat

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

# ZAC 5.12 mails when the taak Aanvullende informatie or Advies extern starts (zac_taken.MAIL_TASKS).
pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster", "mailpit"),
    # One throwaway zaaktype per run.
    pytest.mark.xdist_group("zac-zaakspecifiek"),
]

# ZAC's error codes (ErrorCode) of the refusals.
NOT_AUTORISEERBAAR = "msg.error.zaaktype.not.zaakspecifiek-autoriseerbaar"
WITHOUT_BEHANDELAAR = "msg.error.zaak.without.behandelaar.cannot.be.marked"
NOT_ALLOWED = "msg.error.zaakspecifieke.autorisatie.not.allowed"
CANNOT_BE_LIFTED = "msg.error.zaakspecifieke.autorisatie.cannot.be.lifted"
# ZAC lifts a zaak's zaakspecifieke autorisatie on request from this release on (#7442).
LIFTABLE = (5, 11, 0)
CANNOT_BE_RELEASED = "msg.error.zaakspecifiek.geautoriseerde.zaak.cannot.be.released"
CANNOT_BE_DETACHED = "msg.error.medewerker.cannot.be.detached"
# ZAC marks the zaak of a taak or document in its search results from this release on (#7457); a zaak earlier.
MARKS_TAKEN_AND_DOCUMENTS = (5, 11, 0)
# ZAC adds a medewerker to a marked zaak and lists its medewerkers from this release on (#7348, #7381).
ADDS_MEDEWERKERS = (5, 10, 0)
# ZAC detaches a medewerker from a marked zaak from this release on (#7413).
DETACHES_MEDEWERKERS = (5, 11, 0)
# Before this release ZAC indexes a zaak's completed taken again when it reindexes the zaak's taken (#7595).
DROPS_COMPLETED_TAKEN = (5, 11, 0)
COMPLETED = {"aanvullendeInformatie": "aanvullende-informatie.geleverd-akkoord"}


class Team(NamedTuple):
    """A new group of two behandelaars, logged in to ZAC."""

    group: str
    names: tuple[str, str]
    sessions: tuple[requests.Session, requests.Session]


@pytest.fixture(scope="session", name="zaakspecifiek_zaaktype")
def fixture_zaakspecifiek_zaaktype(
    podiumd_env: Environment,
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    parts: ZaaktypeParts,
    zaaktype_registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> JsonObject:
    """ZAC's zaakafhandelparameters of a throwaway zaaktype that allows zaakspecifieke autorisatie.

    It has the informatieobjecttype e-mail: ZAC 5.12 keeps the mail of Aanvullende informatie as a document.
    """
    need_bootstrap("zac-bpmn-process", "openzaak-iot-email")
    email = email_informatieobjecttype(openzaak, str(test_zaaktype["catalogus"]))
    return make_zac_zaaktype(
        podiumd_env,
        openzaak,
        zaaktype_registry,
        test_zaaktype,
        informatieobjecttypen=(parts.informatieobjecttype, email),
        types=ZAAKSPECIFIEK_TYPES,
    )


@pytest.fixture(name="team")
def fixture_team(podiumd_env: Environment, registry: ResourceRegistry) -> Team:
    """A new Keycloak group with behandelaar rights on podiumd-tests' zaaktypen and two new members."""
    group = make_role_group(podiumd_env, registry, "behandelaar")
    members = (make_group_member(podiumd_env, registry, group), make_group_member(podiumd_env, registry, group))
    sessions = tuple(zac_session(podiumd_env, name, password) for name, password in members)
    return Team(group, (members[0][0], members[1][0]), (sessions[0], sessions[1]))


@pytest.fixture(name="team_zaak")
def fixture_team_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zaakspecifiek_zaaktype: JsonObject,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    team: Team,
) -> JsonObject:
    """A zaak of the zaaktype assigned to the team's group and its first member; cleanup deletes it."""
    zaak = create_zaak(zac, urls["zac"], zaakspecifiek_zaaktype, omschrijving=registry.tagged("zac-zaakspecifiek"))
    # The first member reads the zaak at cleanup: the admin cannot once it is marked.
    clean_up_zaak(team.sessions[0], urls["zac"], openzaak, registry, zaak)
    expect_status(toekennen(zac, urls["zac"], zaak, team.group, team.names[0]), HTTPStatus.OK)
    return zaak


def _mark(http: requests.Session, zac_url: str, zaak: JsonObject, *, marked: bool = True) -> requests.Response:
    """Ask ZAC to set the zaak's zaakspecifieke autorisatie; ZAC's answer."""
    return wijzig_zaak(http, zac_url, zaak, isZaakspecifiekGeautoriseerd=marked)


def _is_found(zoekresultaat: JsonObject | None, *, marked: bool) -> bool:
    """The search listed it, and, if marked, with the lock of a zaakspecifiek geautoriseerde zaak."""
    return zoekresultaat is not None and (not marked or zoekresultaat.get("isZaakspecifiekGeautoriseerd") is True)


def _refused_with(response: requests.Response, code: str) -> None:
    """Assert ZAC refuses the request with this error code."""
    expect_status(response, HTTPStatus.BAD_REQUEST)
    assert response.json().get("message") == code


def _medewerkers(http: requests.Session, zac_url: str, zaak: JsonObject) -> dict[str, bool]:
    """The zaak's zaakspecifiek geautoriseerde medewerkers as ZAC's medewerkers tab lists them, and if each detaches."""
    url = f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/zaakspecifiek-geautoriseerde-medewerkers"
    return {str(m["id"]): bool(m["isDetachable"]) for m in get_entries(http, url)}


def _ontkoppel(
    http: requests.Session, zac_url: str, zaak: JsonObject, medewerker: str, reden: str
) -> requests.Response:
    """Ask ZAC to take the medewerker's access to the marked zaak away, with a reden; ZAC's answer."""
    url = f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/zaakspecifiek-geautoriseerde-medewerkers/{medewerker}"
    return http.delete(url, json={"reden": reden})


def _add_colleague(
    behandelaar: requests.Session, collega: requests.Session, zac_url: str, team: Team, zaak: JsonObject
) -> None:
    """The behandelaar adds the colleague, a candidate of the group, to the marked zaak; the colleague then reaches it."""
    url = f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/zaakspecifiek-geautoriseerde-medewerkers"
    kandidaten = {str(u["id"]) for u in get_entries(behandelaar, f"{url}/kandidaten?groepId={team.group}")}
    assert (team.names[1] in kandidaten, team.names[0] in kandidaten) == (True, False), kandidaten
    added = behandelaar.post(url, json={"groepId": team.group, "medewerkerId": team.names[1]})
    assert expect_status(added, HTTPStatus.OK).json()["id"] == team.names[1]
    assert team.names[1] in _medewerkers(behandelaar, zac_url, zaak)
    assert can_open_zaak(collega, zac_url, zaak)
    wait_until(
        lambda: is_zaak_listed(collega, zac_url, zaak),
        timeout=LIST_TIMEOUT,
        description="the added colleague finds the marked zaak",
    )


@pytest.mark.source("ZAC ZaakRestServiceTest", "Activating zaakspecifieke autorisatie on a zaak.")
@pytest.mark.source("PZW Sprint 82 PZ-12022", "Lifting the zaakspecifieke autorisatie of a zaak (ZAC 5.11).")
@pytest.mark.source(
    "PZW Sprint 82 PZ-12078",
    "ZAC's lists show a lock at a zaakspecifiek geautoriseerde zaak and its taken and documents.",
)
@pytest.mark.scenario("""
    Given a zaak assigned to a behandelaar, with a document
    When the behandelaar marks the zaak as zaakspecifiek geautoriseerd
    Then the behandelaar still opens the zaak and its document, and finds both marked with a lock (document from 5.11)
    And a colleague in the same group, a recordmanager, a raadpleger and a beheerder cannot open them
    And the colleague no longer finds the zaak, until the behandelaar adds the colleague to it (from ZAC 5.10)
    And before ZAC 5.11 the marking cannot be lifted; from 5.11 the behandelaar lifts it and the colleague opens the zaak
""")
def test_marked_zaak_is_reached_only_by_its_behandelaar(  # the zaak, its document and five users
    podiumd_env: Environment,
    urls: dict[str, str],
    team: Team,
    team_zaak: JsonObject,
    zac_as: Callable[[str], requests.Session],
    registry: ResourceRegistry,
) -> None:
    """A zaakspecifiek geautoriseerde zaak and its documents are closed to every other role of the zaaktype."""
    zac_url = urls["zac"]
    behandelaar, collega = team.sessions
    document = uploaded_document(behandelaar, zac_url, team_zaak, registry)
    marked = expect_status(_mark(behandelaar, zac_url, team_zaak), HTTPStatus.OK).json()
    assert marked["isZaakspecifiekGeautoriseerd"] is True

    assert can_open_zaak(behandelaar, zac_url, team_zaak)
    expect_status(behandelaar.get(document_url(zac_url, document)), HTTPStatus.OK)
    others = {"collega": collega, **{role: zac_as(role) for role in ("recordmanager", "raadpleger", "beheerder")}}
    assert [name for name, http in others.items() if can_open_zaak(http, zac_url, team_zaak)] == []
    for http in others.values():
        expect_status(http.get(document_url(zac_url, document)), *REFUSED)
    wait_until(
        lambda: (
            _is_found(zaak_zoekresultaat(behandelaar, zac_url, team_zaak), marked=True)
            and not is_zaak_listed(collega, zac_url, team_zaak)
        ),
        timeout=LIST_TIMEOUT,
        description="the behandelaar finds the zaak marked and the colleague does not find it",
    )
    if not is_older_than(podiumd_env, "zac", MARKS_TAKEN_AND_DOCUMENTS):
        wait_until(
            lambda: _is_found(document_zoekresultaat(behandelaar, zac_url, document), marked=True),
            timeout=LIST_TIMEOUT,
            description="the behandelaar finds the document of the marked zaak, marked",
        )
    if not is_older_than(podiumd_env, "zac", ADDS_MEDEWERKERS):
        _add_colleague(behandelaar, collega, zac_url, team, team_zaak)
    lift = _mark(behandelaar, zac_url, team_zaak, marked=False)
    if is_older_than(podiumd_env, "zac", LIFTABLE):
        _refused_with(lift, CANNOT_BE_LIFTED)
    else:
        assert expect_status(lift, HTTPStatus.OK).json()["isZaakspecifiekGeautoriseerd"] is False
        assert can_open_zaak(collega, zac_url, team_zaak)


@pytest.mark.source("ZAC ZaakspecifiekeAutorisatieService", "Who may mark a zaak, and when it is refused.")
@pytest.mark.scenario("""
    Given a zaak of a zaaktype without zaakspecifieke autorisatie
    Then marking it is refused
    Given a zaak of a zaaktype with zaakspecifieke autorisatie, assigned to a group only
    Then marking it is refused until it has a behandelaar
    And a colleague who is not its behandelaar cannot mark it
    When its behandelaar marks it
    Then it can be handed over, but not released without a behandelaar
""")
def test_marking_is_refused_without_its_conditions(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    team: Team,
    team_zaak: JsonObject,
) -> None:
    """ZAC marks only a zaak of an enabled zaaktype, with a behandelaar, at the request of that behandelaar."""
    zac_url = urls["zac"]
    behandelaar, collega = team.sessions
    _refused_with(_mark(zac, zac_url, zac_zaak()), NOT_AUTORISEERBAAR)
    expect_status(toekennen(zac, zac_url, team_zaak, team.group, None), HTTPStatus.OK)
    _refused_with(_mark(behandelaar, zac_url, team_zaak), WITHOUT_BEHANDELAAR)
    expect_status(toekennen(zac, zac_url, team_zaak, team.group, team.names[0]), HTTPStatus.OK)
    _refused_with(_mark(collega, zac_url, team_zaak), NOT_ALLOWED)

    expect_status(_mark(behandelaar, zac_url, team_zaak), HTTPStatus.OK)
    _refused_with(toekennen(behandelaar, zac_url, team_zaak, team.group, None), CANNOT_BE_RELEASED)


@pytest.mark.source(
    "PZW Sprint 82 PZ-12793", "A zaakspecifiek geautoriseerde zaak is not verdeeld to a group without a behandelaar."
)
@pytest.mark.scenario("""
    Given two zaken of the team's group with the same behandelaar, one marked zaakspecifiek geautoriseerd
    When the beheerder verdeelt both to the group without a behandelaar
    Then the unmarked zaak has no behandelaar
    And the marked zaak keeps its behandelaar
""")
def test_marked_zaak_is_skipped_when_verdeeld_without_a_behandelaar(  # the zaaktype, the team and the zaak
    zac: requests.Session,
    urls: dict[str, str],
    zaakspecifiek_zaaktype: JsonObject,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    team: Team,
    team_zaak: JsonObject,
) -> None:
    """Verdelen to a group alone skips a marked zaak and releases the others (ZaakService.assignZaakFromBatch)."""
    zac_url = urls["zac"]
    behandelaar = team.sessions[0]
    gewoon = create_zaak(zac, zac_url, zaakspecifiek_zaaktype, omschrijving=registry.tagged("zac-zaakspecifiek"))
    clean_up_zaak(zac, zac_url, openzaak, registry, gewoon)
    expect_status(toekennen(zac, zac_url, gewoon, team.group, team.names[0]), HTTPStatus.OK)
    expect_status(_mark(behandelaar, zac_url, team_zaak), HTTPStatus.OK)

    uuids = [str(gewoon["uuid"]), str(team_zaak["uuid"])]
    expect_status(verdelen(zac, zac_url, uuids, team.group, None), HTTPStatus.NO_CONTENT)
    wait_until(
        lambda: assignment(read_zaak(behandelaar, zac_url, str(gewoon["uuid"]))) == (team.group, None),
        timeout=LIST_TIMEOUT,
        description=f"zaak {gewoon['identificatie']} verdeeld to {team.group}",
    )
    assert assignment(read_zaak(behandelaar, zac_url, str(team_zaak["uuid"]))) == (team.group, team.names[0])


@pytest.mark.source("ZAC ZaakService.assignZaak", "The replaced behandelaar keeps access to the zaak.")
@pytest.mark.source(
    "PZW Sprint 82 PZ-12046",
    "The behandelaar takes a former behandelaar's access to a zaakspecifiek geautoriseerde zaak away (ZAC 5.11).",
)
@pytest.mark.scenario("""
    Given a zaak its behandelaar marked as zaakspecifiek geautoriseerd
    When the behandelaar hands it over to a colleague
    Then the colleague and the former behandelaar open the zaak, and a recordmanager still cannot
    And the colleague cannot take the access of the current behandelaar away
    When the colleague takes the former behandelaar's access away with a reden
    Then the former behandelaar no longer opens the zaak, and the zaak's historie shows the reden
""")
def test_handed_over_zaak_stays_open_to_the_former_behandelaar(  # the zaak and three users
    podiumd_env: Environment,
    urls: dict[str, str],
    registry: ResourceRegistry,
    team: Team,
    team_zaak: JsonObject,
    zac_as: Callable[[str], requests.Session],
) -> None:
    """A handover authorises the former behandelaar as zaakspecifiek geautoriseerde medewerker, who can be detached."""
    zac_url = urls["zac"]
    behandelaar, collega = team.sessions
    expect_status(_mark(behandelaar, zac_url, team_zaak), HTTPStatus.OK)
    assert not can_open_zaak(collega, zac_url, team_zaak)
    expect_status(toekennen(behandelaar, zac_url, team_zaak, team.group, team.names[1]), HTTPStatus.OK)
    assert (can_open_zaak(collega, zac_url, team_zaak), can_open_zaak(behandelaar, zac_url, team_zaak)) == (True, True)
    assert not can_open_zaak(zac_as("recordmanager"), zac_url, team_zaak)
    if is_older_than(podiumd_env, "zac", DETACHES_MEDEWERKERS):
        return
    assert _medewerkers(collega, zac_url, team_zaak) == {team.names[0]: True, team.names[1]: False}
    _refused_with(_ontkoppel(collega, zac_url, team_zaak, team.names[1], "ptest"), CANNOT_BE_DETACHED)
    reden = registry.tagged("ontkoppeld")
    expect_status(_ontkoppel(collega, zac_url, team_zaak, team.names[0], reden), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert not can_open_zaak(behandelaar, zac_url, team_zaak)
    assert reden in {line.get("toelichting") for line in zaak_historie(collega, zac_url, team_zaak)}


def _complete_and_reindex(
    behandelaar: requests.Session, zac_url: str, team: Team, zaak: JsonObject, taak: JsonObject
) -> None:
    """The behandelaar assigns the taak to themselves, completes it, then has a second taak in Mijn taken."""
    zac_taken.toekennen_taak(behandelaar, zac_url, taak, team.group, team.names[0])
    zac_taken.complete_task(behandelaar, zac_url, zac_taken.read_taak(behandelaar, zac_url, str(taak["id"])), COMPLETED)
    # Assigning a taak of a marked zaak reindexes all of the zaak's taken.
    started = zac_taken.start_human_task(behandelaar, zac_url, zaak, zac_taken.AANVULLENDE_INFORMATIE, team.group)
    expect_status(started, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    tweede = zac_taken.open_task(behandelaar, zac_url, str(zaak["uuid"]), zac_taken.AANVULLENDE_INFORMATIE)
    zac_taken.toekennen_taak(behandelaar, zac_url, tweede, team.group, team.names[0])
    wait_until(
        lambda: is_taak_listed(behandelaar, zac_url, tweede, alleenMijnTaken=True),
        timeout=LIST_TIMEOUT,
        description="the second taak in the behandelaar's Mijn taken",
    )


@pytest.mark.source("ZAC taak-rechten.rego", "A taak of a marked zaak is open only to the zaak's authorised users.")
@pytest.mark.source(
    "PZW Sprint 82 PZ-12078",
    "ZAC's lists show a lock at a zaakspecifiek geautoriseerde zaak and its taken and documents.",
)
@pytest.mark.source(
    "PZW Sprint 82 PZ-13176",
    "A completed taak of a zaakspecifiek geautoriseerde zaak leaves Aan mij toegewezen taken and Mijn taken (ZAC 5.11).",
)
@pytest.mark.scenario("""
    Given a zaak with a taak Aanvullende informatie, which its behandelaar marks as zaakspecifiek geautoriseerd
    When the behandelaar, a colleague in the same group and a beheerder open the taak
    Then only the behandelaar may read it and finds it marked with a lock (from ZAC 5.11); the colleague does not find it
    When the behandelaar assigns the taak to themselves, completes it and assigns themselves a second taak
    Then the second taak is in the behandelaar's Mijn taken and the completed one is not
""")
def test_taak_of_a_marked_zaak_is_read_only_by_its_behandelaar(  # the zaak, its taken and three users
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    zaakspecifiek_zaaktype: JsonObject,
    team: Team,
    team_zaak: JsonObject,
    zac_as: Callable[[str], requests.Session],
) -> None:
    """taak-rechten.rego's zaak_allowed: lezen of the taak only for the marked zaak's behandelaar."""
    zac_url, uuid = urls["zac"], str(team_zaak["uuid"])
    behandelaar, collega = team.sessions
    zac_taken.activate_human_tasks(zac, zac_url, str(section(zaakspecifiek_zaaktype, "zaaktype")["uuid"]))
    started = zac_taken.start_human_task(behandelaar, zac_url, team_zaak, zac_taken.AANVULLENDE_INFORMATIE, team.group)
    expect_status(started, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    taak = zac_taken.open_task(behandelaar, zac_url, uuid, zac_taken.AANVULLENDE_INFORMATIE)
    expect_status(_mark(behandelaar, zac_url, team_zaak), HTTPStatus.OK)

    readers = {"behandelaar": behandelaar, "collega": collega, "beheerder": zac_as("beheerder")}
    allowed = {name: http.get(f"{zac_url}/rest/taken/{taak['id']}").ok for name, http in readers.items()}
    assert allowed == {"behandelaar": True, "collega": False, "beheerder": False}
    marked = not is_older_than(podiumd_env, "zac", MARKS_TAKEN_AND_DOCUMENTS)
    wait_until(
        lambda: (
            _is_found(taak_zoekresultaat(behandelaar, zac_url, taak), marked=marked)
            and not is_taak_listed(collega, zac_url, taak)
        ),
        timeout=LIST_TIMEOUT,
        description="the behandelaar finds the taak of the marked zaak and the colleague does not",
    )
    if is_older_than(podiumd_env, "zac", DROPS_COMPLETED_TAKEN):
        return
    _complete_and_reindex(behandelaar, zac_url, team, team_zaak, taak)
    assert not is_taak_listed(behandelaar, zac_url, taak, alleenMijnTaken=True), "the completed taak is in Mijn taken"


# ZAC grants a BPMN user task's assignee the zaakspecifieke autorisatie of the zaak from this release on (#7693).
GRANTS_BPMN_TAAKBEHANDELAAR = (5, 12, 0)


@pytest.mark.requires("cluster")
@pytest.mark.source(
    "PZW Sprint 83 PZ-13199",
    "A behandelaar that the BPMN process assigns a taak to gets the zaak's zaakspecifieke autorisatie automatically.",
)
@pytest.mark.scenario("""
    Given a zaak of a zaakspecifiek autoriseerbaar zaaktype that runs podiumd-tests' BPMN process
    And its behandelaar, a member of a new group, has marked it zaakspecifiek geautoriseerd
    And so the test admin cannot open it
    When the behandelaar completes the intake on the route whose next taak the process assigns to the test admin
    Then the test admin can open the zaak
""")
def test_bpmn_taak_behandelaar_gets_the_zaakspecifieke_autorisatie(  # the zaaktype's parts
    podiumd_env: Environment,
    urls: dict[str, str],
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    parts: ZaaktypeParts,
    registry: ResourceRegistry,
) -> None:
    """ZacCreateUserTaskInterceptor grants the HARDCODED taak's behandelaar access to the marked zaak.

    ZAC reads a user's zaaktypen at login: the sessions start after the zaaktype exists.
    """
    skip_older_than(podiumd_env, "zac", GRANTS_BPMN_TAAKBEHANDELAAR, "no grant to a BPMN taak's behandelaar")
    zac_url = urls["zac"]
    parameters = make_zac_zaaktype(
        podiumd_env,
        openzaak,
        registry,
        test_zaaktype,
        informatieobjecttypen=(parts.informatieobjecttype,),
        types=ZAAKSPECIFIEK_TYPES,
        bpmn_process=PROCESS_KEY,
    )
    group = make_role_group(podiumd_env, registry, "behandelaar")
    naam, password = make_group_member(podiumd_env, registry, group)
    admin, behandelaar = zac_as_admin(podiumd_env), zac_session(podiumd_env, naam, password)
    zaak = create_zaak(admin, zac_url, parameters, omschrijving=registry.tagged("zac-bpmn-zsa"))
    # The behandelaar reads the zaak at cleanup: the admin cannot once it is marked.
    clean_up_zaak(behandelaar, zac_url, openzaak, registry, zaak)
    expect_status(toekennen(admin, zac_url, zaak, group, naam), HTTPStatus.OK)
    expect_status(_mark(behandelaar, zac_url, zaak), HTTPStatus.OK)
    assert not can_open_zaak(admin, zac_url, zaak)

    complete_intake(behandelaar, zac_url, zaak, (group, naam), **{TOEWIJZING: True})
    assert assignment(zac_taken.open_task(behandelaar, zac_url, str(zaak["uuid"]), HARDCODED)) == HARDCODED_TO
    assert can_open_zaak(admin, zac_url, zaak)
