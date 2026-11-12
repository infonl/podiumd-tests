"""ZAC: a CMMN zaak through intake, afhandelen and heropenen, as ZAC's REST API does it for the UI.

Intake afronden and afhandelen are CMMN user events (`/rest/planitems/doUserEventListenerPlanItem`); heropenen and
afbreken are actions on the zaak. The zaak is of the estate's productaanvraag zaaktype (fixture zac_zaak).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import after_period
from podiumd_tests.seed.openzaak import today
from podiumd_tests.zac import HEROPEND
from podiumd_tests.zac import afbreken
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import afsluiten
from podiumd_tests.zac import heropenen
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import resultaattypen
from podiumd_tests.zac import user_event

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject

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
    # The list of zaakafhandelparameters leaves this field out; the zaaktype's own read has it.
    zaaktype = section(closed, "zaaktype")["uuid"]
    parameters = expect_status(zac.get(f"{urls['zac']}/rest/zaakafhandelparameters/{zaaktype}"), HTTPStatus.OK).json()
    expected = section(parameters, "zaakNietOntvankelijkResultaattype").get("id")
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
        response = afhandelen(zac, urls["zac"], zaak, str(resultaattype["id"]), brondatum=brondatum)
        expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
        closed = read_zaak(zac, urls["zac"], str(zaak["uuid"]))
        assert (section(closed, "status").get("naam"), closed["isOpen"]) == ("Afgerond", False)
        assert section(section(closed, "resultaat"), "resultaattype").get("id") == resultaattype["id"]
        in_open_zaak = openzaak_productaanvraag.get(f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}")
        archief = openzaak.get(f"{CATALOGI}/resultaattypen/{resultaattype['id']}")
        assert in_open_zaak["archiefnominatie"] == archief["archiefnominatie"]
        assert closed.get("archiefNominatie") == str(archief["archiefnominatie"]).upper()
        assert closed.get("archiefActiedatum") == in_open_zaak["archiefactiedatum"]
        bron = {"afgehandeld": in_open_zaak["einddatum"], "eigenschap": brondatum}
        afleiding = str(section(archief, "brondatumArchiefprocedure").get("afleidingswijze"))
        if bron.get(afleiding):
            expected = after_period(str(bron[afleiding]), str(archief["archiefactietermijn"]))
            assert in_open_zaak["archiefactiedatum"] == expected


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
