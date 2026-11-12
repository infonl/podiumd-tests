"""ZAC: zaaknotities, through the REST API its UI calls.

The tests with a second user log in as bootstrap's test behandelaar (fixture zac_as), whose role covers only the BPMN
test zaaktype.
"""

from __future__ import annotations

from datetime import date
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import ZAC_ROLE_USERS
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.zac import can_open_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

ZAC_TEAM = pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
)
BEHANDELAAR = "behandelaar"
ZAC_21 = pytest.mark.xfail(
    strict=True,
    reason="[zac-21] ZAC 5.9.1 checks only notitie_rechten on notities (NoteRestService), not their author or zaak; not "
    "yet reported upstream",
)


def _notities_url(zac_url: str) -> str:
    return f"{zac_url}/rest/notities"


def _notities(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """The zaak's notities as ZAC lists them for the session's user."""
    return get_entries(http, f"{_notities_url(zac_url)}/zaken/{zaak['uuid']}")


def _add(http: requests.Session, zac_url: str, zaak: JsonObject, tekst: str, auteur: str) -> requests.Response:
    """Add a notitie to the zaak in the name of auteur, as ZAC's UI sends it; ZAC's answer."""
    body = {"zaakUUID": zaak["uuid"], "tekst": tekst, "gebruikersnaamMedewerker": auteur}
    return http.post(_notities_url(zac_url), json=body)


@pytest.mark.tc("ZAC-029", "ZAC-030", "ZAC-031")
@pytest.mark.source("draaiboek ZAC-029", "A zaaknotitie can be added, changed and deleted (ZAC-029, -030, -031).")
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds, changes and then deletes a zaaknotitie
    Then the zaak lists the notitie with its text after adding
    And the zaak lists the changed text after changing
    And the zaak lists no notitie after deleting
""")
def test_note_can_be_added_changed_and_deleted(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """A zaaknotitie is listed with its text, then with the changed text, and is gone after deleting it."""
    zaak = zac_zaak()

    def texts() -> list[str]:
        return [str(n["tekst"]) for n in _notities(zac, urls["zac"], zaak)]

    tekst = registry.tagged("notitie")
    note = expect_status(_add(zac, urls["zac"], zaak, tekst, ADMIN.username), HTTPStatus.OK).json()
    assert texts() == [tekst]
    changed = registry.tagged("gewijzigd")
    expect_status(zac.patch(_notities_url(urls["zac"]), json={**note, "tekst": changed}), HTTPStatus.OK)
    assert texts() == [changed]
    expect_status(zac.delete(f"{_notities_url(urls['zac'])}/{note['id']}"), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert texts() == []


@ZAC_TEAM
@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype
    When the test admin and a behandelaar each add a notitie
    Then each notitie shows today's date and its author
    And each user may change only their own notitie
""")
def test_notitie_records_its_date_and_author(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """tijdstipLaatsteWijziging is today, gebruikersnaamMedewerker the author; bewerkenToegestaan for the author only."""
    behandelaar, naam = zac_as(BEHANDELAAR), ZAC_ROLE_USERS[BEHANDELAAR].username
    for http, auteur in ((zac, ADMIN.username), (behandelaar, naam)):
        expect_status(_add(http, urls["zac"], bpmn_zaak, registry.tagged(auteur), auteur), HTTPStatus.OK)
    listed = _notities(behandelaar, urls["zac"], bpmn_zaak)
    today = date.today().isoformat()  # noqa: DTZ011  # ZAC's local date
    assert {str(n["tijdstipLaatsteWijziging"])[:10] for n in listed} == {today}
    assert {(n["tekst"], n["gebruikersnaamMedewerker"]) for n in listed} == {
        (registry.tagged(auteur), auteur) for auteur in (ADMIN.username, naam)
    }
    assert {str(n["gebruikersnaamMedewerker"]): n["bewerkenToegestaan"] for n in listed} == {
        ADMIN.username: False,
        naam: True,
    }


@ZAC_21
@ZAC_TEAM
@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype with a notitie of the test admin
    When a behandelaar of that zaaktype changes or deletes that notitie, or adds one in the name of the test admin
    Then the test admin's notities are as before
""")
@pytest.mark.parametrize("actie", ["wijzigen", "verwijderen", "toevoegen"])
def test_notitie_of_another_user_is_not_changed_or_deleted(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    registry: ResourceRegistry,
    actie: str,
) -> None:
    """After the behandelaar's PATCH, DELETE or POST naming the admin, the admin has only the one notitie, unchanged."""
    tekst = registry.tagged("notitie")
    note = expect_status(_add(zac, urls["zac"], bpmn_zaak, tekst, ADMIN.username), HTTPStatus.OK).json()
    behandelaar, notities = zac_as(BEHANDELAAR), _notities_url(urls["zac"])
    if actie == "wijzigen":
        response = behandelaar.patch(notities, json={**note, "tekst": registry.tagged("gewijzigd")})
    elif actie == "verwijderen":
        response = behandelaar.delete(f"{notities}/{note['id']}")
    else:
        response = _add(behandelaar, urls["zac"], bpmn_zaak, registry.tagged("namens"), ADMIN.username)
    listed = _notities(zac, urls["zac"], bpmn_zaak)
    van_admin = [n["tekst"] for n in listed if n["gebruikersnaamMedewerker"] == ADMIN.username]
    assert van_admin == [tekst], describe(response)


@ZAC_21
@ZAC_TEAM
@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given a zaak of a zaaktype outside the behandelaar's domain, with a notitie
    When the behandelaar reads the zaak's notities
    Then ZAC refuses it, as it refuses to open the zaak
""")
def test_notities_of_a_zaak_the_user_may_not_open_are_refused(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    registry: ResourceRegistry,
) -> None:
    """The behandelaar, who cannot open the zaak, gets 401 or 403 for its notities."""
    zaak = zac_zaak()
    expect_status(_add(zac, urls["zac"], zaak, registry.tagged("notitie"), ADMIN.username), HTTPStatus.OK)
    behandelaar = zac_as(BEHANDELAAR)
    assert not can_open_zaak(behandelaar, urls["zac"], zaak)
    response = behandelaar.get(f"{_notities_url(urls['zac'])}/zaken/{zaak['uuid']}")
    assert response.status_code in REFUSED, describe(response)
