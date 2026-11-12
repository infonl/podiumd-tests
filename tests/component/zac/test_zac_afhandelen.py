"""ZAC: a CMMN zaak through intake, afhandelen and heropenen, as ZAC's REST API does it for the UI.

Intake afronden and afhandelen are CMMN user events (`/rest/planitems/doUserEventListenerPlanItem`); heropenen and
afbreken are actions on the zaak. The zaak is of the estate's productaanvraag zaaktype (fixture zac_zaak).
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import section
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import after_period
from podiumd_tests.seed.openzaak import today
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import HEROPEND
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import NIET_ONTVANKELIJK_REDEN
from podiumd_tests.zac import afbreken
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import afsluiten
from podiumd_tests.zac import heropenen
from podiumd_tests.zac import logged_in_user
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import resultaattypen
from podiumd_tests.zac import user_event
from podiumd_tests.zac import verdelen
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac import zaak_historie
from podiumd_tests.zac import zoned_brondatum
from podiumd_tests.zac_documents import lock_document
from podiumd_tests.zac_documents import unlock_document
from podiumd_tests.zac_documents import uploaded_document

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
    ),
]


def _status(zac: requests.Session, zac_url: str, zaak: JsonObject) -> str:
    return str(section(read_zaak(zac, zac_url, str(zaak["uuid"])), "status").get("naam"))


def _afhandelen(zac: requests.Session, zac_url: str, zaak: JsonObject) -> JsonObject:
    """Afhandelen with the first resultaattype that needs no besluit; the zaak as ZAC shows it after."""
    expect_status(afhandelen(zac, zac_url, zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    return read_zaak(zac, zac_url, str(zaak["uuid"]))


def _assert_archief(openzaak: ApiClient, closed: JsonObject, in_open_zaak: JsonObject, eigenschap: str | None) -> None:
    """The closed zaak has its resultaattype's archiefnominatie, and the archiefactiedatum Open Zaak derived.

    That date is checked against the resultaattype for afleidingswijze afgehandeld, and eigenschap with its date.
    """
    resultaattype = section(section(closed, "resultaat"), "resultaattype")["id"]
    archief = openzaak.get(f"{CATALOGI}/resultaattypen/{resultaattype}")
    assert in_open_zaak["archiefnominatie"] == archief["archiefnominatie"]
    assert closed.get("archiefNominatie") == str(archief["archiefnominatie"]).upper()
    assert closed.get("archiefActiedatum") == in_open_zaak["archiefactiedatum"]
    bron = {"afgehandeld": in_open_zaak["einddatum"], "eigenschap": eigenschap}
    afleiding = str(section(archief, "brondatumArchiefprocedure").get("afleidingswijze"))
    if bron.get(afleiding):
        expected = after_period(str(bron[afleiding]), str(archief["archiefactietermijn"]))
        assert in_open_zaak["archiefactiedatum"] == expected


def _niet_ontvankelijk(zac: requests.Session, zac_url: str, zaak: JsonObject) -> object:
    """The id of the niet-ontvankelijk resultaattype of the zaak's zaakafhandelparameters.

    The list of zaakafhandelparameters leaves this field out; the zaaktype's own read has it.
    """
    zaaktype = section(zaak, "zaaktype")["uuid"]
    parameters = expect_status(zac.get(f"{zac_url}/rest/zaakafhandelparameters/{zaaktype}"), HTTPStatus.OK).json()
    return section(parameters, "zaakNietOntvankelijkResultaattype").get("id")


@pytest.mark.scenario("""
    Given a new zaak in ZAC, in the intake
    When the behandelaar finishes the intake as ontvankelijk
    Then the zaak is In behandeling
    And ZAC offers to afhandelen it
""")
def test_ontvankelijk_intake_puts_the_zaak_in_behandeling(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """INTAKE_AFRONDEN with zaakOntvankelijk gives status In behandeling and the user event ZAAK_AFHANDELEN."""
    zaak = zac_zaak()
    assert _status(zac, urls["zac"], zaak) == "Intake"
    afronden_intake(zac, urls["zac"], zaak)
    assert _status(zac, urls["zac"], zaak) == "In behandeling"
    listeners = zac.get(f"{urls['zac']}/rest/planitems/zaak/{zaak['uuid']}/userEventListenerPlanItems").json()
    assert [item.get("userEventListenerActie") for item in listeners] == ["ZAAK_AFHANDELEN"]


@pytest.mark.scenario("""
    Given a new zaak in ZAC, in the intake
    When the behandelaar finishes the intake as niet ontvankelijk
    Then the zaak is closed with the niet-ontvankelijk resultaat of its zaakafhandelparameters
""")
def test_niet_ontvankelijk_intake_closes_the_zaak(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """INTAKE_AFRONDEN without zaakOntvankelijk closes the zaak with zaakNietOntvankelijkResultaattype."""
    zaak = zac_zaak()
    fields = {"zaakOntvankelijk": False, "resultaatToelichting": "podiumd-tests"}
    expect_status(
        user_event(zac, urls["zac"], str(zaak["uuid"]), "INTAKE_AFRONDEN", **fields),
        HTTPStatus.OK,
        HTTPStatus.NO_CONTENT,
    )
    closed = read_zaak(zac, urls["zac"], str(zaak["uuid"]))
    assert closed["isOpen"] is False
    expected = _niet_ontvankelijk(zac, urls["zac"], closed)
    assert section(section(closed, "resultaat"), "resultaattype")["id"] == expected


@pytest.mark.scenario("""
    Given the resultaattypen of the zaaktype that need no besluit
    When the behandelaar afhandelt a zaak in behandeling with each of them
    Then each zaak is Afgerond and closed, with that resultaat
    And ZAC shows the archiefnominatie of the resultaattype and the archiefactiedatum Open Zaak derived
    And that archiefactiedatum is the archiefactietermijn after the brondatum
""")
def test_afhandelen_closes_the_zaak_with_its_resultaat(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    zac_parameters: JsonObject,
    openzaak: ApiClient,
    openzaak_productaanvraag: ApiClient,
) -> None:
    """ZAAK_AFHANDELEN per resultaattype sets status Afgerond, the resultaat, its archiefnominatie and -actiedatum."""
    for resultaattype in resultaattypen(zac, urls["zac"], zac_parameters):
        if resultaattype.get("besluitVerplicht"):
            continue
        zaak = zac_zaak()
        afronden_intake(zac, urls["zac"], zaak)
        # afleidingswijze eigenschap: ZAC stores the brondatum as the zaak's eigenschap.
        brondatum = today() if resultaattype.get("datumKenmerkVerplicht") else None
        zoned = zoned_brondatum(brondatum) if brondatum else None
        response = afhandelen(zac, urls["zac"], zaak, str(resultaattype["id"]), brondatum=zoned)
        expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
        closed = read_zaak(zac, urls["zac"], str(zaak["uuid"]))
        assert (section(closed, "status").get("naam"), closed["isOpen"]) == ("Afgerond", False)
        assert section(section(closed, "resultaat"), "resultaattype").get("id") == resultaattype["id"]
        in_open_zaak = openzaak_productaanvraag.get(f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}")
        _assert_archief(openzaak, closed, in_open_zaak, brondatum)


@pytest.mark.scenario("""
    Given an afgehandelde zaak in ZAC
    When a user with the right to reopen heropent it with a reden
    Then the zaak is Heropend and open, without resultaat and archiefactiedatum
    And it cannot be afgebroken
    But it can be afgehandeld again
""")
def test_heropend_zaak_loses_its_resultaat_and_can_be_closed_again(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """heropenen: status Heropend, resultaat and archiefActiedatum cleared; afbreken refused; afsluiten closes again."""
    zaak = zac_zaak()
    afronden_intake(zac, urls["zac"], zaak)
    closed = _afhandelen(zac, urls["zac"], zaak)
    if not section(closed, "rechten").get("heropenen"):
        pytest.skip("the test admin may not reopen zaken of this zaaktype in the estate's PABC dataset")
    reopened = expect_status(heropenen(zac, urls["zac"], zaak), HTTPStatus.OK).json()
    assert (section(reopened, "status").get("naam"), reopened["isOpen"]) == (HEROPEND, True)
    assert (reopened.get("resultaat"), reopened.get("archiefActiedatum")) == (None, None)
    expect_status(afbreken(zac, urls["zac"], zaak), *REFUSED)
    again = expect_status(afsluiten(zac, urls["zac"], zaak), HTTPStatus.OK)
    assert again.json()["isOpen"] is False


@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC
    When the behandelaar afhandelt it without choosing a resultaat
    Then ZAC refuses it and the zaak stays open
""")
def test_afhandelen_needs_a_resultaat(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """ZAAK_AFHANDELEN without resultaattypeUuid answers 400 and leaves the zaak open."""
    zaak = zac_zaak()
    afronden_intake(zac, urls["zac"], zaak)
    response = user_event(zac, urls["zac"], str(zaak["uuid"]), "ZAAK_AFHANDELEN")
    expect_status(response, HTTPStatus.BAD_REQUEST)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is True


@pytest.mark.scenario("""
    Given an open zaak in ZAC
    When the behandelaar breaks it off as niet ontvankelijk
    Then the zaak is Afgerond and closed, with the reden as toelichting of its status
    And it has the niet-ontvankelijk resultaat of its zaakafhandelparameters
    And ZAC shows the archiefnominatie of that resultaat and the archiefactiedatum Open Zaak derived
""")
def test_afgebroken_zaak_is_afgerond_with_its_archiefactiedatum(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak: ApiClient,
    openzaak_productaanvraag: ApiClient,
) -> None:
    """Afbreken sets status Afgerond with ZAC's reden, the niet-ontvankelijk resultaat, archiefnominatie and -actiedatum."""
    zaak = zac_zaak()
    closed = expect_status(afbreken(zac, urls["zac"], zaak), HTTPStatus.OK).json()
    status = section(closed, "status")
    assert (status.get("naam"), status.get("toelichting"), closed["isOpen"]) == (
        "Afgerond",
        NIET_ONTVANKELIJK_REDEN,
        False,
    )
    assert section(section(closed, "resultaat"), "resultaattype")["id"] == _niet_ontvankelijk(zac, urls["zac"], closed)
    in_open_zaak = openzaak_productaanvraag.get(f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}")
    _assert_archief(openzaak, closed, in_open_zaak, None)


@pytest.mark.xfail(
    strict=True,
    reason="[zac-31] ZAC 5.9.1 answers 500 to afbreken without zaakbeeindigRedenId (NumberFormatException in "
    "ZaakRestService.terminateZaak); not yet reported upstream",
)
@pytest.mark.scenario("""
    Given an open zaak in ZAC
    When the behandelaar breaks it off without a reden
    Then ZAC refuses it as a bad request
    And the zaak stays open
""")
def test_afbreken_needs_a_reden(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """Afbreken without zaakbeeindigRedenId answers 400 and leaves the zaak open."""
    zaak = zac_zaak()
    response = zac.patch(f"{urls['zac']}/rest/zaken/zaak/{zaak['uuid']}/afbreken", json={})
    assert response.status_code == HTTPStatus.BAD_REQUEST, describe(response)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is True


@pytest.mark.parametrize("beeindigen", [afhandelen, afbreken], ids=["afhandelen", "afbreken"])
@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC with a document the behandelaar vergrendeld
    When the behandelaar afhandelt or afbreekt the zaak
    Then it is refused and the zaak stays open
    When the behandelaar ontgrendelt the document
    Then the zaak can be afgehandeld or afgebroken
""")
def test_vergrendeld_document_holds_off_closing_the_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    registry: ResourceRegistry,
    beeindigen: Callable[[requests.Session, str, JsonObject], requests.Response],
) -> None:
    """Open Zaak refuses the eindstatus with 400 while a document of the zaak is locked."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry)
    lock_document(zac, urls["zac"], zaak, document, registry)
    afronden_intake(zac, urls["zac"], zaak)
    expect_status(beeindigen(zac, urls["zac"], zaak), HTTPStatus.BAD_REQUEST)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is True

    expect_status(unlock_document(zac, urls["zac"], zaak, document), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    expect_status(beeindigen(zac, urls["zac"], zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is False


def _dutch(day: str) -> str:
    """A date as ZAC's historie shows it: dd-mm-yyyy."""
    return date.fromisoformat(day).strftime("%d-%m-%Y")


@pytest.mark.scenario("""
    Given a new zaak in ZAC
    When the test admin verdeelt it to themselves, moves its fatale datum, finishes the intake, afhandelt and heropent it
    Then the historie names the test admin as the user of each step
    And it shows the behandelaar linked and the old and new fatale datum
    And it shows the statuses In behandeling, Afgerond and Heropend, and the resultaat added and removed
""")
def test_historie_records_each_step_with_its_user_and_values(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], zac_group: str
) -> None:
    """Each action gives historie lines with door, oudeWaarde and nieuweWaarde, all by the test admin."""
    zac_url, zaak = urls["zac"], zac_zaak()
    naam = logged_in_user(zac, zac_url)["naam"]
    expect_status(verdelen(zac, zac_url, [str(zaak["uuid"])], zac_group, ADMIN.username), HTTPStatus.NO_CONTENT)

    def is_verdeeld() -> bool:
        lines = zaak_historie(zac, zac_url, zaak)
        return any((line.get("actie"), line.get("nieuweWaarde")) == ("GEKOPPELD", naam) for line in lines)

    wait_until(is_verdeeld, timeout=LIST_TIMEOUT, description=f"zaak {zaak['identificatie']} verdeeld in its historie")
    fataal = str(zaak["uiterlijkeEinddatumAfdoening"])
    later = (date.fromisoformat(fataal) + timedelta(days=3)).isoformat()
    expect_status(wijzig_zaak(zac, zac_url, zaak, uiterlijkeEinddatumAfdoening=later), HTTPStatus.OK)
    afronden_intake(zac, zac_url, zaak)
    resultaat = section(section(_afhandelen(zac, zac_url, zaak), "resultaat"), "resultaattype")["naam"]
    expect_status(heropenen(zac, zac_url, zaak), HTTPStatus.OK)

    lines = zaak_historie(zac, zac_url, zaak)
    assert {line.get("door") for line in lines} == {naam}
    found = {
        (line.get("actie"), line.get("attribuutLabel"), line.get("oudeWaarde"), line.get("nieuweWaarde"))
        for line in lines
    }
    expected = {
        ("GEWIJZIGD", "uiterlijkeEinddatumAfdoening", _dutch(fataal), _dutch(later)),
        ("GEWIJZIGD", "status", None, "In behandeling"),
        ("GEWIJZIGD", "status", None, "Afgerond"),
        ("GEWIJZIGD", "status", None, HEROPEND),
        ("GEKOPPELD", "resultaat", None, resultaat),
        ("ONTKOPPELD", "resultaat", resultaat, None),
    }
    assert expected <= found, sorted(map(str, found))
