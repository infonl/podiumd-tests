"""ZAC's handling of a zaak, through the REST API its UI calls: start, notes, suspension, extension, abort, betrokkenen.

The zaak is of the zaaktype ZAC handles productaanvragen for (profile setting productaanvraag_zaaktype);
the test admin is ZAC beheerder of every domain.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import person_key
from podiumd_tests.zac import read_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

# ZAC indexes a zaak in Solr after Open Notificaties tells it about the change.
INDEX_TIMEOUT = 60
_, _, BEDRIJF = IDENTITIES
# The reason ZAC always offers for aborting a zaak.
NIET_ONTVANKELIJK = "ZAAK_NIET_ONTVANKELIJK"


@pytest.mark.tc("ZAC-006", "ZAC-010", "ZAC-019", "ZAC-022")
def test_new_zaak_keeps_the_chosen_fields(
    zac_zaak: Callable[..., JsonObject], zac_parameters: JsonObject, registry: ResourceRegistry
) -> None:
    """A zaak started with a zaaktype, an earlier startdatum, a communicatiekanaal and a toelichting has them."""
    startdatum = (date.today() - timedelta(days=3)).isoformat()  # noqa: DTZ011  # ZAC's dates are local dates
    toelichting = registry.tagged("toelichting")
    zaak = zac_zaak(startdatum=startdatum, communicatiekanaal="E-mail", toelichting=toelichting)
    chosen = {"startdatum": startdatum, "communicatiekanaal": "E-mail", "toelichting": toelichting}
    assert {k: zaak.get(k) for k in chosen} == chosen
    assert section(zaak, "zaaktype")["uuid"] == section(zac_parameters, "zaaktype")["uuid"]


@pytest.mark.tc("ZAC-029", "ZAC-030", "ZAC-031")
def test_note_can_be_added_changed_and_deleted(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """A zaaknotitie is listed with its text, then with the changed text, and is gone after deleting it."""
    notes = f"{urls['zac']}/rest/notities"
    zaak = zac_zaak()

    def texts() -> list[str]:
        return [str(n["tekst"]) for n in entries(expect_status(zac.get(f"{notes}/zaken/{zaak['uuid']}"), 200).json())]

    body = {"zaakUUID": zaak["uuid"], "tekst": registry.tagged("notitie"), "gebruikersnaamMedewerker": ADMIN.username}
    note = expect_status(zac.post(notes, json=body), HTTPStatus.OK).json()
    assert texts() == [body["tekst"]]
    changed = registry.tagged("gewijzigd")
    expect_status(zac.patch(notes, json={**note, "tekst": changed}), HTTPStatus.OK)
    assert texts() == [changed]
    expect_status(zac.delete(f"{notes}/{note['id']}"), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert texts() == []


@pytest.mark.tc("ZAC-042", "ZAC-043")
def test_suspended_zaak_resumes_and_cannot_be_suspended_again(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """After a suspension and its resumption, ZAC refuses a second suspension."""
    zaak = zac_zaak()
    base = f"{urls['zac']}/rest/zaken/zaak/{zaak['uuid']}"
    suspended = expect_status(zac.patch(f"{base}/suspend", json={"reason": "test", "numberOfDays": 5}), 200).json()
    assert suspended["isOpgeschort"]
    expect_status(zac.patch(f"{base}/resume", json={"reason": "test"}), HTTPStatus.OK)
    assert not read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpgeschort"]
    again = zac.patch(f"{base}/suspend", json={"reason": "nogmaals", "numberOfDays": 5})
    expect_status(again, HTTPStatus.FORBIDDEN, HTTPStatus.BAD_REQUEST)


@pytest.mark.tc("ZAC-044")
def test_extension_moves_the_planned_and_final_dates(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    zac_parameters: JsonObject,
    zac_zaak: Callable[..., JsonObject],
) -> None:
    """Extending a zaak by some days moves its uiterlijke einddatum afdoening by that many days."""
    zaaktype = openzaak.get(f"{CATALOGI}/zaaktypen/{section(zac_parameters, 'zaaktype')['uuid']}")
    if not zaaktype.get("verlengingMogelijk"):
        pytest.skip(f"zaaktype {zaaktype['identificatie']} allows no verlenging")
    zaak = zac_zaak()
    final = date.fromisoformat(str(zaak["uiterlijkeEinddatumAfdoening"])) + timedelta(days=10)
    body = {
        "redenVerlenging": "test",
        "duurDagen": 10,
        "takenVerlengen": False,
        "uiterlijkeEinddatumAfdoening": final.isoformat(),
    }
    extended = zac.patch(f"{urls['zac']}/rest/zaken/zaak/{zaak['uuid']}/verlenging", json=body)
    assert expect_status(extended, HTTPStatus.OK).json()["uiterlijkeEinddatumAfdoening"] == final.isoformat()


def abort(zac: requests.Session, zac_url: str, zaak: JsonObject) -> None:
    """Abort the zaak in ZAC as niet ontvankelijk."""
    body = {"zaakbeeindigRedenId": NIET_ONTVANKELIJK}
    response = zac.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/afbreken", json=body)
    expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)


@pytest.mark.tc("ZAC-045")
def test_aborted_zaak_is_closed(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """Aborting a zaak (niet ontvankelijk) closes it."""
    zaak = zac_zaak()
    abort(zac, urls["zac"], zaak)
    assert not read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"]


@pytest.mark.tc("ZAC-062")
def test_closed_zaak_is_listed_among_the_closed_zaken(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """ZAC's search for closed zaken lists a zaak once it is closed (ZAC indexes it on Open Notificaties' zaken kanaal)."""
    zaak = zac_zaak()
    abort(zac, urls["zac"], zaak)
    query = {
        "page": 0,
        "rows": 10,
        "type": "ZAAK",
        "alleenAfgeslotenZaken": True,
        "zoeken": {"ZAAK_IDENTIFICATIE": zaak["identificatie"]},
    }

    def listed() -> bool:
        found = expect_status(zac.put(f"{urls['zac']}/rest/zoeken/list", json=query), HTTPStatus.OK).json()
        return any(r.get("identificatie") == zaak["identificatie"] for r in entries(found["resultaten"]))

    wait_until(listed, timeout=INDEX_TIMEOUT, description=f"zaak {zaak['identificatie']} among the closed zaken")


@pytest.mark.tc("ZAC-047", "ZAC-048")
def test_betrokkenen_with_the_same_and_different_roles_are_listed(
    zac: requests.Session, urls: dict[str, str], zac_parameters: JsonObject, zac_zaak: Callable[..., JsonObject]
) -> None:
    """A person in two roles and a company in one of them are all listed with the zaak."""
    zaak = zac_zaak()
    zaaktype = section(zac_parameters, "zaaktype")["uuid"]
    roltypen = {
        r["naam"]: r["uuid"]
        for r in entries(zac.get(f"{urls['zac']}/rest/klanten/roltype/{zaaktype}/betrokkene").json())
    }
    company = {
        "type": "VN",
        "kvkNummer": BEDRIJF.attributes["kvk"][0],
        "vestigingsnummer": BEDRIJF.attributes["vestigingsnummer"][0],
    }
    wanted = [("Belanghebbende", "persoon"), ("Contactpersoon", "persoon"), ("Belanghebbende", "bedrijf")]
    for rol, who in wanted:

        def add(rol: str = rol, who: str = who) -> requests.Response:
            person = {"type": "BSN", "temporaryPersonId": person_key(zac, urls["zac"], EREBOS)}
            body = {
                "zaakUUID": zaak["uuid"],
                "roltypeUUID": roltypen[rol],
                "roltoelichting": "test",
                "betrokkeneIdentificatie": person if who == "persoon" else company,
            }
            return zac.post(f"{urls['zac']}/rest/zaken/betrokkene", json=body)

        response = add()
        if response.status_code == HTTPStatus.GONE:
            # ZAC 5.4.5 keeps handing out a temporaryPersonId it forgot 12 h after its last read (PLAN §13);
            # the 410 clears it and a new lookup gets a fresh one, as for a user who tries again.
            response = add()
        expect_status(response, HTTPStatus.OK)
    listed = entries(expect_status(zac.get(f"{urls['zac']}/rest/zaken/zaak/{zaak['uuid']}/betrokkene"), 200).json())
    assert sorted(str(b.get("roltype")) for b in listed) == sorted(r for r, _ in wanted)
