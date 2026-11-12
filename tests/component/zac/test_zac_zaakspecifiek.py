"""ZAC's zaakspecifieke autorisatie: a behandelaar marks a zaak so only its authorised medewerkers reach it.

On a throwaway zaaktype with the eigenschap and roltype ZAC requires, in a new group with two new behandelaars.
The application role zaakspecifiek_geautoriseerd is not in PodiumD's PABC dataset, so its holders are not tested.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import NamedTuple

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.zac_zaaktype import ZAAKSPECIFIEK_TYPES
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import AANVULLENDE_INFORMATIE
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import activate_human_tasks
from podiumd_tests.zac import can_open_zaak
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import is_taak_listed
from podiumd_tests.zac import is_zaak_listed
from podiumd_tests.zac import open_task
from podiumd_tests.zac import start_human_task
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac import zac_session
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import uploaded_document

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster"),
    # One throwaway zaaktype per run.
    pytest.mark.xdist_group("zac-zaakspecifiek"),
]

# ZAC's error codes (ErrorCode) of the refusals.
NOT_AUTORISEERBAAR = "msg.error.zaaktype.not.zaakspecifiek-autoriseerbaar"
WITHOUT_BEHANDELAAR = "msg.error.zaak.without.behandelaar.cannot.be.marked"
NOT_ALLOWED = "msg.error.zaakspecifieke.autorisatie.not.allowed"
CANNOT_BE_LIFTED = "msg.error.zaakspecifieke.autorisatie.cannot.be.lifted"
CANNOT_BE_RELEASED = "msg.error.zaakspecifiek.geautoriseerde.zaak.cannot.be.released"


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
    """ZAC's zaakafhandelparameters of a throwaway zaaktype that allows zaakspecifieke autorisatie."""
    need_bootstrap("zac-bpmn-process")
    return make_zac_zaaktype(
        podiumd_env,
        openzaak,
        zaaktype_registry,
        test_zaaktype,
        informatieobjecttypen=(parts.informatieobjecttype,),
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


def _refused_with(response: requests.Response, code: str) -> None:
    """Assert ZAC refuses the request with this error code."""
    expect_status(response, HTTPStatus.BAD_REQUEST)
    assert response.json().get("message") == code


@pytest.mark.source("ZAC ZaakRestServiceTest", "Activating zaakspecifieke autorisatie on a zaak.")
@pytest.mark.scenario("""
    Given a zaak assigned to a behandelaar, with a document
    When the behandelaar marks the zaak as zaakspecifiek geautoriseerd
    Then the behandelaar still opens the zaak and its document, and finds the zaak
    And a colleague in the same group, a recordmanager, a raadpleger and a beheerder cannot open them
    And the colleague no longer finds the zaak
    And the marking cannot be lifted
""")
def test_marked_zaak_is_reached_only_by_its_behandelaar(
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
        lambda: is_zaak_listed(behandelaar, zac_url, team_zaak) and not is_zaak_listed(collega, zac_url, team_zaak),
        timeout=LIST_TIMEOUT,
        description="the behandelaar finds the marked zaak and the colleague does not",
    )
    _refused_with(_mark(behandelaar, zac_url, team_zaak, marked=False), CANNOT_BE_LIFTED)


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


@pytest.mark.source("ZAC ZaakService.assignZaak", "The replaced behandelaar keeps access to the zaak.")
@pytest.mark.scenario("""
    Given a zaak its behandelaar marked as zaakspecifiek geautoriseerd
    When the behandelaar hands it over to a colleague
    Then the colleague opens the zaak
    And the former behandelaar still opens it
    And a recordmanager still cannot
""")
def test_handed_over_zaak_stays_open_to_the_former_behandelaar(
    urls: dict[str, str], team: Team, team_zaak: JsonObject, zac_as: Callable[[str], requests.Session]
) -> None:
    """A handover of a marked zaak authorises the former behandelaar as zaakspecifiek geautoriseerde medewerker."""
    zac_url = urls["zac"]
    behandelaar, collega = team.sessions
    expect_status(_mark(behandelaar, zac_url, team_zaak), HTTPStatus.OK)
    assert not can_open_zaak(collega, zac_url, team_zaak)
    expect_status(toekennen(behandelaar, zac_url, team_zaak, team.group, team.names[1]), HTTPStatus.OK)
    assert can_open_zaak(collega, zac_url, team_zaak)
    assert can_open_zaak(behandelaar, zac_url, team_zaak)
    assert not can_open_zaak(zac_as("recordmanager"), zac_url, team_zaak)


@pytest.mark.source("ZAC taak-rechten.rego", "A taak of a marked zaak is open only to the zaak's authorised users.")
@pytest.mark.scenario("""
    Given a zaak with a taak Aanvullende informatie, which its behandelaar marks as zaakspecifiek geautoriseerd
    When the behandelaar, a colleague in the same group and a beheerder open the taak
    Then only the behandelaar may read it
    And the colleague does not find it in the takenlijst
""")
def test_taak_of_a_marked_zaak_is_read_only_by_its_behandelaar(  # the zaak, its taak and three users
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
    activate_human_tasks(zac, zac_url, str(section(zaakspecifiek_zaaktype, "zaaktype")["uuid"]))
    started = start_human_task(behandelaar, zac_url, team_zaak, AANVULLENDE_INFORMATIE, team.group)
    expect_status(started, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    taak = open_task(behandelaar, zac_url, uuid, AANVULLENDE_INFORMATIE)
    expect_status(_mark(behandelaar, zac_url, team_zaak), HTTPStatus.OK)

    readers = {"behandelaar": behandelaar, "collega": collega, "beheerder": zac_as("beheerder")}
    allowed = {name: http.get(f"{zac_url}/rest/taken/{taak['id']}").ok for name, http in readers.items()}
    assert allowed == {"behandelaar": True, "collega": False, "beheerder": False}
    wait_until(
        lambda: is_taak_listed(behandelaar, zac_url, taak) and not is_taak_listed(collega, zac_url, taak),
        timeout=LIST_TIMEOUT,
        description="the behandelaar finds the taak of the marked zaak and the colleague does not",
    )
