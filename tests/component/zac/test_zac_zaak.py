"""ZAC's handling of a zaak, through the REST API its UI calls: start, suspension, extension, abort, betrokkenen.

The zaak is of the zaaktype ZAC handles productaanvragen for (profile setting productaanvraag_zaaktype);
the test admin is ZAC beheerder of every domain.
"""

from __future__ import annotations

import re

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.pdf import pdfa_problems
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import BEVESTIGING_NIET_VERSTUURD
from podiumd_tests.zac import DUE_DATES
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import afbreken
from podiumd_tests.zac import assignment
from podiumd_tests.zac import hervatten
from podiumd_tests.zac import is_zaak_listed
from podiumd_tests.zac import opschorten
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import send_with_person
from podiumd_tests.zac import verlengen
from podiumd_tests.zac import wait_in_werkvoorraad
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac import zaak_historie
from podiumd_tests.zac_beheer import communicatiekanalen
from podiumd_tests.zac_betrokkenen import add_betrokkene
from podiumd_tests.zac_betrokkenen import betrokkene_roltype
from podiumd_tests.zac_betrokkenen import betrokkenen
from podiumd_tests.zac_betrokkenen import wijzig_initiator
from podiumd_tests.zac_documents import convert_to_pdf
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_documents import zaak_documents

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

_, _, BEDRIJF = IDENTITIES
SUSPENSION_DAYS = 5
# ZAC's reden for the group and behandelaar it links to a zaak it creates.
AANMAKEN_ZAAK = "Aanmaken zaak"
# ZAC's toelichting of a status it sets.
STATUS_GEWIJZIGD = "Status gewijzigd"


def _zaak_url(urls: dict[str, str], zaak: JsonObject) -> str:
    return f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}"


def _dates(openzaak: ApiClient, urls: dict[str, str], zaak: JsonObject) -> tuple[date, ...]:
    """The zaak's DUE_DATES in Open Zaak."""
    found = openzaak.get(_zaak_url(urls, zaak))
    return tuple(date.fromisoformat(str(found[field])) for field in DUE_DATES)


def _days(duration: object) -> int | None:
    """Days of an ISO 8601 duration of only days (P14D); None for any other."""
    found = re.fullmatch(r"P(\d+)D", str(duration or ""))
    return int(found.group(1)) if found else None


@pytest.mark.tc("ZAC-006", "ZAC-010", "ZAC-019", "ZAC-022")
@pytest.mark.source(
    "draaiboek ZAC-006",
    "A new zaak: the zaaktype, startdatum, communicatiekanaal and toelichting can be chosen (ZAC-006, -010, -019, -022).",
)
@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios: a new zaak with a group and behandelaar, and its historie.",
)
@pytest.mark.scenario("""
    Given a behandelaar is logged in to ZAC
    When the behandelaar starts a zaak with a zaaktype, an earlier startdatum, a communicatiekanaal and a toelichting
    And assigns it to their group and to themselves
    Then the zaak has the chosen zaaktype, startdatum, communicatiekanaal, toelichting, group and behandelaar
    And its historie records that the zaak was created and linked to the group and the behandelaar
""")
def test_new_zaak_keeps_the_chosen_fields(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    zac_parameters: JsonObject,
    zac_group: str,
    registry: ResourceRegistry,
) -> None:
    """A new zaak has its chosen fields and assignment; its historie has the zaak and both rollen linked at creation."""
    startdatum = (date.today() - timedelta(days=3)).isoformat()  # noqa: DTZ011  # ZAC's dates are local dates
    toelichting = registry.tagged("toelichting")
    assigned = {"groep": {"id": zac_group, "naam": zac_group}, "behandelaar": {"id": ADMIN.username}}
    zaak = zac_zaak(startdatum=startdatum, communicatiekanaal="E-mail", toelichting=toelichting, **assigned)
    chosen = {"startdatum": startdatum, "communicatiekanaal": "E-mail", "toelichting": toelichting}
    assert {k: zaak.get(k) for k in chosen} == chosen
    assert section(zaak, "zaaktype")["uuid"] == section(zac_parameters, "zaaktype")["uuid"]
    assert assignment(zaak) == (zac_group, ADMIN.username)
    historie = {
        (line.get("actie"), line.get("nieuweWaarde")): line.get("toelichting")
        for line in zaak_historie(zac, urls["zac"], zaak)
    }
    assert ("AANGEMAAKT", zaak["identificatie"]) in historie
    linked = [historie.get(("GEKOPPELD", section(zaak, rol).get("naam"))) for rol in ("groep", "behandelaar")]
    assert linked == [AANMAKEN_ZAAK, AANMAKEN_ZAAK], historie


@pytest.mark.source("podiumd-tests", "A status change of a zaak leaves its rollen linked, also in its historie.")
@pytest.mark.xfail(
    strict=True,
    reason="[open-zaak-13] Open Zaak 1.29.3 audits every rol as destroyed (and notifies rol destroy) when ZAC sets a "
    "status through zaak_bijwerken without rollen; ZAC's historie shows them ONTKOPPELD; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a new zaak in ZAC, assigned to a group and a behandelaar
    When ZAC gives the zaak its first status
    Then the historie shows the status change
    And it shows no group or behandelaar as unlinked
""")
def test_status_change_unlinks_no_rol_in_the_historie(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], zac_group: str
) -> None:
    """Once the historie has the status change, it has no ONTKOPPELD line."""
    zaak = zac_zaak(groep={"id": zac_group, "naam": zac_group}, behandelaar={"id": ADMIN.username})

    def status_changed() -> list[JsonObject] | None:
        lines = zaak_historie(zac, urls["zac"], zaak)
        changed = any(
            line.get("actie") == "GEWIJZIGD" and line.get("toelichting") == STATUS_GEWIJZIGD for line in lines
        )
        return lines if changed else None

    lines = wait_until(status_changed, timeout=INDEX_TIMEOUT, description=f"status change of {zaak['identificatie']}")
    assert [line for line in lines if line.get("actie") == "ONTKOPPELD"] == []


@pytest.mark.requires("opennotificaties")
@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios: zaakgegevens change with one save, dates only when changed, and the new"
    " behandelaar finds the zaak in Mijn zaken.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC with a group and no behandelaar
    When the behandelaar changes its group, behandelaar, communicatiekanaal, vertrouwelijkheidaanduiding and toelichting in one save
    Then the zaak has the new values and keeps its startdatum, streefdatum and fatale datum
    And the zaak appears in the new behandelaar's Mijn zaken
    When the behandelaar moves the startdatum, streefdatum and fatale datum a week later
    Then the zaak has those dates
""")
def test_zaakgegevens_change_with_one_save(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    zac_group: str,
    registry: ResourceRegistry,
) -> None:
    """One edit changes the assignment and the zaakgegevens and keeps the dates, as ZAC's form sends them; a second moves the dates.

    ZAC lists Mijn zaken from its search index, which follows Open Notificaties' zaken kanaal.
    """
    zac_url = urls["zac"]
    zaak = zac_zaak()
    dates = {field: zaak[field] for field in ("startdatum", "einddatumGepland", "uiterlijkeEinddatumAfdoening")}
    kanaal = next(kanaal for kanaal in communicatiekanalen(zac, zac_url) if kanaal != zaak["communicatiekanaal"])
    changed = {
        "communicatiekanaal": kanaal,
        "vertrouwelijkheidaanduiding": "VERTROUWELIJK",
        "toelichting": registry.tagged("gewijzigd"),
    }
    assigned = {"groep": {"id": zac_group, "naam": zac_group}, "behandelaar": {"id": ADMIN.username}}
    expect_status(wijzig_zaak(zac, zac_url, zaak, **dates, **changed, **assigned), HTTPStatus.OK)
    edited = read_zaak(zac, zac_url, str(zaak["uuid"]))
    assert {field: edited.get(field) for field in (*changed, *dates)} == {**changed, **dates}
    assert assignment(edited) == (zac_group, ADMIN.username)
    wait_until(
        lambda: is_zaak_listed(zac, zac_url, zaak, alleenMijnZaken=True),
        timeout=INDEX_TIMEOUT,
        description=f"zaak {zaak['identificatie']} in Mijn zaken",
    )
    later = {field: (date.fromisoformat(str(day)) + timedelta(days=7)).isoformat() for field, day in dates.items()}
    expect_status(wijzig_zaak(zac, zac_url, zaak, **later), HTTPStatus.OK)
    moved = read_zaak(zac, zac_url, str(zaak["uuid"]))
    assert {field: moved.get(field) for field in later} == later


@pytest.mark.xfail(
    strict=True,
    reason="[zac-2] ZAC 5.4.5 and 5.9.1 answer 500 to a zaak without startdatum (NullPointerException in"
    " calculateDoorlooptijden); PZ-13090",
)
@pytest.mark.source(
    "podiumd-tests", "Found while porting ZAC-010: ZAC's UI always sends a startdatum, its API answers 500 without one."
)
@pytest.mark.scenario("""
    Given a behandelaar is logged in to ZAC
    When the behandelaar starts a zaak without a startdatum
    Then ZAC refuses the zaak as a bad request, or starts it today
""")
def test_zaak_without_startdatum_is_refused_or_starts_today(zac_zaak: Callable[..., JsonObject]) -> None:
    """ZAC refuses a zaak without startdatum with 400, or starts it today."""
    refused, zaak = "", {}
    try:
        zaak = zac_zaak(startdatum=None)
    except UnexpectedStatusError as error:
        refused = str(error)
    if refused:
        assert ": HTTP 400," in refused, refused
    else:
        assert zaak.get("startdatum") == date.today().isoformat()  # noqa: DTZ011  # ZAC's dates are local dates


@pytest.mark.requires("opennotificaties")
@pytest.mark.source(
    "ZAC features/2-zaken-toevoegen.feature",
    "Bob creates a zaak and sees it, its initiator, that no acknowledgment was sent, and the zaak in the werkvoorraad.",
)
@pytest.mark.source("ZAC features/8-personen.feature", "Bob opens the initiator's person details from the zaak.")
@pytest.mark.scenario("""
    Given a new zaak in ZAC
    When the behandelaar adds a person from the BRP as initiator
    Then the initiator's person details show that person's BSN
    And the zaak shows that no ontvangstbevestiging was sent
    And the zaak appears among the open zaken in the werkvoorraad
""")
def test_zaak_with_an_initiator_is_in_the_werkvoorraad(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """A new zaak with a BRP person as initiator shows the person, lacks an ontvangstbevestiging, and is in the werkvoorraad.

    The werkvoorraad is ZAC's search for open zaken; ZAC indexes the zaak on Open Notificaties' zaken kanaal.
    """
    zaak = zac_zaak()

    def add(identificatie: JsonObject) -> requests.Response:
        return wijzig_initiator(zac, urls["zac"], zaak, identificatie, None)

    initiator = section(
        expect_status(send_with_person(zac, urls["zac"], EREBOS, add), HTTPStatus.OK).json(), "initiatorIdentificatie"
    )
    person = zac.get(f"{urls['zac']}/rest/klanten/person/{initiator['temporaryPersonId']}")
    assert expect_status(person, HTTPStatus.OK).json()["bsn"] == EREBOS
    assert BEVESTIGING_NIET_VERSTUURD in strings(zaak.get("indicaties"))
    wait_in_werkvoorraad(zac, urls["zac"], zaak)


@pytest.mark.tc("ZAC-042", "ZAC-043")
@pytest.mark.source(
    "draaiboek ZAC-042",
    "A suspended zaak can be resumed, and a resumed zaak cannot be suspended again (ZAC-042, -043).",
)
@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios: opschorten shifts the dates and records the opschorting in Open Zaak.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar suspends the zaak for 5 days with a reden
    Then its streefdatum and fatale datum are 5 days later, and Open Zaak records the opschorting and its reden
    When the behandelaar resumes the zaak the same day
    Then both dates move back by the 5 days not used, and Open Zaak keeps that it was opgeschort before
    And the historie records each date change with the reden of the opschorting or the hervatting
    And ZAC refuses to suspend it a second time
""")
def test_suspended_zaak_resumes_and_cannot_be_suspended_again(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
) -> None:
    """Opschorten moves both dates and sets Open Zaak's opschorting; hervatten moves them back by the unused days."""
    zaak = zac_zaak()
    before = _dates(openzaak_productaanvraag, urls, zaak)
    suspended = opschorten(zac, urls["zac"], zaak, SUSPENSION_DAYS, "podiumd-tests op")
    assert expect_status(suspended, HTTPStatus.OK).json()["isOpgeschort"]
    in_open_zaak = openzaak_productaanvraag.get(_zaak_url(urls, zaak))
    assert _dates(openzaak_productaanvraag, urls, zaak) == tuple(
        day + timedelta(days=SUSPENSION_DAYS) for day in before
    )
    opschorting = section(in_open_zaak, "opschorting")
    assert (opschorting.get("indicatie"), opschorting.get("reden")) == (True, "podiumd-tests op")

    expect_status(hervatten(zac, urls["zac"], zaak, "podiumd-tests her"), HTTPStatus.OK)
    assert not read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpgeschort"]
    assert _dates(openzaak_productaanvraag, urls, zaak) == before
    resumed = section(openzaak_productaanvraag.get(_zaak_url(urls, zaak)), "opschorting")
    assert (resumed.get("indicatie"), resumed.get("eerdereOpschorting")) == (False, True)
    historie = {(line.get("attribuutLabel"), line.get("toelichting")) for line in zaak_historie(zac, urls["zac"], zaak)}
    reasons = ("Opschorting: podiumd-tests op", "Hervatting: podiumd-tests her")
    assert {(field, reason) for field in DUE_DATES for reason in reasons} <= historie, historie
    again = opschorten(zac, urls["zac"], zaak, SUSPENSION_DAYS, "nogmaals")
    expect_status(again, HTTPStatus.FORBIDDEN, HTTPStatus.BAD_REQUEST)


@pytest.mark.source("podiumd-tests", "ZAC team's regression scenarios: opschorten and verlengen require a reden.")
@pytest.mark.parametrize("actie", ["opschorten", "verlengen"])
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar suspends or extends the zaak without a reden
    Then ZAC refuses it as a bad request
    And the zaak is neither opgeschort nor verlengd, and keeps its streefdatum and fatale datum
""")
def test_zaak_is_not_suspended_or_extended_without_a_reden(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
    actie: str,
) -> None:
    """ZAC answers 400 to opschorten and verlengen without a reden, and changes nothing.

    Open Zaak refuses the missing reden; ZAC accepts an empty one.
    """
    zaak = zac_zaak()
    before = _dates(openzaak_productaanvraag, urls, zaak)
    send = opschorten if actie == "opschorten" else verlengen
    expect_status(send(zac, urls["zac"], zaak, SUSPENSION_DAYS, None), HTTPStatus.BAD_REQUEST)
    indicaties = strings(read_zaak(zac, urls["zac"], str(zaak["uuid"])).get("indicaties"))
    assert {"OPSCHORTING", "VERLENGD"}.isdisjoint(indicaties), indicaties
    assert _dates(openzaak_productaanvraag, urls, zaak) == before


@pytest.mark.source(
    "podiumd-tests", "ZAC team's regression scenarios: a zaak is opgeschort only once, whatever the reden."
)
@pytest.mark.xfail(
    strict=True,
    reason="[zac-19] ZAC 5.9.1 tells an earlier opschorting by its stored reden and accepts a blank reden, so a zaak "
    "suspended and resumed with blank redenen can be suspended again; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar suspends it with a reden of only a space and resumes it with an empty reden
    Then ZAC refuses to suspend it a second time
""")
def test_zaak_suspended_with_a_blank_reden_is_not_suspended_again(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """A second opschorten is refused; a refused blank reden at the first opschorten also passes."""
    zaak = zac_zaak()
    if opschorten(zac, urls["zac"], zaak, SUSPENSION_DAYS, " ").status_code != HTTPStatus.OK:
        return
    expect_status(hervatten(zac, urls["zac"], zaak, ""), HTTPStatus.OK)
    again = opschorten(zac, urls["zac"], zaak, SUSPENSION_DAYS, "nogmaals")
    expect_status(again, HTTPStatus.FORBIDDEN, HTTPStatus.BAD_REQUEST)


@pytest.mark.tc("ZAC-044")
@pytest.mark.source("draaiboek ZAC-044", "The streefdatum and fatale datum of a zaak can be extended, once.")
@pytest.mark.scenario("""
    Given a zaak in ZAC of a zaaktype that allows verlenging
    When the behandelaar extends the zaak by 10 days with a reden
    Then its streefdatum and fatale datum are 10 days later, and Open Zaak records the verlenging
    And ZAC refuses to extend it a second time
""")
def test_extension_moves_the_planned_and_final_dates(
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    openzaak_productaanvraag: ApiClient,
    zac_parameters: JsonObject,
    zac_zaak: Callable[..., JsonObject],
) -> None:
    """Verlengen moves both dates by its days, is stored in Open Zaak, and is allowed once."""
    zaaktype = openzaak.get(f"{CATALOGI}/zaaktypen/{section(zac_parameters, 'zaaktype')['uuid']}")
    if not zaaktype.get("verlengingMogelijk"):
        pytest.skip(f"zaaktype {zaaktype['identificatie']} allows no verlenging")
    zaak = zac_zaak()
    planned, final = (day + timedelta(days=10) for day in _dates(openzaak_productaanvraag, urls, zaak))
    expect_status(verlengen(zac, urls["zac"], zaak, 10), HTTPStatus.OK)
    assert _dates(openzaak_productaanvraag, urls, zaak) == (planned, final)
    verlenging = section(openzaak_productaanvraag.get(_zaak_url(urls, zaak)), "verlenging")
    assert (verlenging.get("reden"), verlenging.get("duur")) == ("podiumd-tests", "P10D")
    expect_status(verlengen(zac, urls["zac"], zaak, 5), HTTPStatus.FORBIDDEN, HTTPStatus.BAD_REQUEST)


@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios: the streefdatum and fatale datum come from the zaaktype's doorlooptijden.",
)
@pytest.mark.scenario("""
    Given a zaaktype with a servicenorm and a doorlooptijd in days
    When the behandelaar starts a zaak of it in ZAC
    Then its streefdatum is the startdatum plus the servicenorm
    And its fatale datum is the startdatum plus the doorlooptijd
""")
def test_new_zaak_dates_come_from_the_zaaktype(
    urls: dict[str, str],
    openzaak: ApiClient,
    openzaak_productaanvraag: ApiClient,
    zac_parameters: JsonObject,
    zac_zaak: Callable[..., JsonObject],
) -> None:
    """einddatumGepland is startdatum + servicenorm, uiterlijkeEinddatumAfdoening startdatum + doorlooptijd."""
    zaaktype = openzaak.get(f"{CATALOGI}/zaaktypen/{section(zac_parameters, 'zaaktype')['uuid']}")
    servicenorm, doorlooptijd = (_days(zaaktype.get(field)) for field in ("servicenorm", "doorlooptijd"))
    if servicenorm is None or doorlooptijd is None:
        pytest.skip(f"zaaktype {zaaktype['identificatie']} has no servicenorm and doorlooptijd in days")
    zaak = zac_zaak()
    start = date.fromisoformat(str(openzaak_productaanvraag.get(_zaak_url(urls, zaak))["startdatum"]))
    planned = start + timedelta(days=servicenorm)
    assert _dates(openzaak_productaanvraag, urls, zaak) == (planned, start + timedelta(days=doorlooptijd))


@pytest.mark.tc("ZAC-045", "ZAC-062")
# ZAC updates its search index from Open Notificaties' notifications.
@pytest.mark.requires("opennotificaties")
@pytest.mark.source(
    "draaiboek ZAC-045", "A zaak can be aborted, and then shows in the werkvoorraad of closed zaken (ZAC-045, -062)."
)
@pytest.mark.scenario("""
    Given an open zaak in ZAC
    When the behandelaar aborts the zaak as niet ontvankelijk
    Then the zaak is closed
    And the zaak appears among the closed zaken
""")
def test_aborted_zaak_is_closed_and_listed_among_the_closed_zaken(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """Aborting a zaak (niet ontvankelijk) closes it; ZAC's search for closed zaken then lists it.

    ZAC indexes the zaak on Open Notificaties' zaken kanaal.
    """
    zaak = zac_zaak()
    expect_status(afbreken(zac, urls["zac"], zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert not read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"]

    def is_listed() -> bool:
        return is_zaak_listed(zac, urls["zac"], zaak, alleenAfgeslotenZaken=True)

    wait_until(is_listed, timeout=INDEX_TIMEOUT, description=f"zaak {zaak['identificatie']} among the closed zaken")


@pytest.mark.tc("ZAC-047", "ZAC-048")
@pytest.mark.source(
    "draaiboek ZAC-047",
    "Several betrokkenen with the same and different roles are linked to the zaak and shown with their role (ZAC-047, -048).",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds a person as belanghebbende and as contactpersoon
    And adds a company as belanghebbende
    Then the zaak lists all three betrokkenen with their roles
""")
def test_betrokkenen_with_the_same_and_different_roles_are_listed(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """A person in two roles and a company in one of them are all listed with the zaak."""
    zaak = zac_zaak()
    roltypen = {rol: betrokkene_roltype(zac, urls["zac"], zaak, rol) for rol in ("belanghebbende", "contactpersoon")}
    company = {
        "type": "VN",
        "kvkNummer": BEDRIJF.attributes["kvk"][0],
        "vestigingsnummer": BEDRIJF.attributes["vestigingsnummer"][0],
    }
    wanted = [("belanghebbende", "persoon"), ("contactpersoon", "persoon"), ("belanghebbende", "bedrijf")]
    for rol, who in wanted:

        def add(identificatie: JsonObject, rol: str = rol) -> requests.Response:
            return add_betrokkene(zac, urls["zac"], zaak, roltypen[rol], identificatie)

        response = send_with_person(zac, urls["zac"], EREBOS, add) if who == "persoon" else add(company)
        expect_status(response, HTTPStatus.OK)
    listed = betrokkenen(zac, urls["zac"], zaak)
    assert sorted(str(b.get("roltype")) for b in listed) == sorted(str(roltypen[r]["naam"]) for r, _ in wanted)


@pytest.mark.tc("ZAC-058")
@pytest.mark.source("draaiboek ZAC-058", "A document can be deleted.")
@pytest.mark.scenario("""
    Given a document uploaded to a zaak in ZAC
    When the behandelaar deletes the document
    Then the zaak no longer lists the document
""")
def test_document_can_be_deleted(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """A document uploaded to the zaak in ZAC is gone from the zaak after ZAC deletes it."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry)
    assert document["uuid"] in [d.get("uuid") for d in zaak_documents(zac, urls["zac"], zaak)]
    deleted = zac.delete(
        document_url(urls["zac"], document),
        json={"zaakUuid": zaak["uuid"], "reden": "test"},
    )
    expect_status(deleted, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert document["uuid"] not in [d.get("uuid") for d in zaak_documents(zac, urls["zac"], zaak)]


@pytest.mark.tc("ZAC-056")
@pytest.mark.source(
    "draaiboek ZAC-056", "A document can be edited directly; Word saves it automatically as the new version."
)
@pytest.mark.parametrize(
    ("suffix", "app"), [("docx", "ms-word"), ("excel", "ms-excel"), ("powerpoint", "ms-powerpoint")]
)
@pytest.mark.scenario("""
    Given a Word, Excel or PowerPoint document in bewerking on a zaak in ZAC
    When the behandelaar opens it for editing in its Office application
    And the application saves the edited document
    Then the document has a new version
    And the download gives the saved content
""")
def test_word_saves_an_edited_document_as_a_new_version(
    zac: requests.Session,
    http: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    registry: ResourceRegistry,
    suffix: str,
    app: str,
) -> None:
    """The Office application opens the document through ZAC's WebDAV link and saves it as the next version.

    The link's token alone gives access; ZAC keeps it in the memory of the pod that handed it out.
    """
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry, suffix=suffix, status="in_bewerking")
    documents = document_url(urls["zac"], document)
    of_zaak = {"zaak": str(zaak["uuid"])}
    link = str(expect_status(zac.get(f"{documents}/edit", params=of_zaak), HTTPStatus.OK).json())
    scheme, _, url = link.partition(":")
    assert scheme == app
    assert url.startswith(f"{urls['zac']}/webdav/folder/")
    expect_status(http.put(url, data=b"versie 2"), HTTPStatus.CREATED, HTTPStatus.NO_CONTENT)
    current = expect_status(zac.get(documents, params=of_zaak), HTTPStatus.OK).json()
    assert current["versie"] == int(str(document["versie"])) + 1
    assert expect_status(zac.get(f"{documents}/download"), HTTPStatus.OK).content == b"versie 2"


@pytest.mark.tc("ZAC-039")
@pytest.mark.source(
    "draaiboek ZAC-039", "A document sent by post outside ZAC gets the indication verzonden in the documents overview."
)
@pytest.mark.scenario("""
    Given a definitief PDF document on a zaak in ZAC
    When the behandelaar records that the document was sent by post
    Then the zaak's documents mark the document as verzonden
""")
def test_sent_document_is_marked_verzonden(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """A PDF marked as sent (by post, outside ZAC) has the indication VERZONDEN in the zaak's documents.

    ZAC lets only definitief, not confidential PDFs be sent.
    """
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry, suffix="pdf")
    body = {
        "zaakUuid": zaak["uuid"],
        "verzenddatum": date.today().isoformat(),  # noqa: DTZ011  # a local date
        "informatieobjecten": [document["uuid"]],
        "toelichting": "per post",
    }
    expect_status(zac.post(f"{urls['zac']}/rest/informatieobjecten/informatieobjecten/verzenden", json=body), 200, 204)
    listed = {str(d.get("uuid")): d for d in zaak_documents(zac, urls["zac"], zaak)}
    assert "VERZONDEN" in strings(listed[str(document["uuid"])].get("indicaties"))


@pytest.mark.source(
    "podiumd-tests",
    "ZAC converts a Word document to PDF through its office converter (gotenberg); helm-charts #633 updates gotenberg.",
)
@pytest.mark.parametrize("suffix", ["word", "large-word", "excel", "powerpoint"])
@pytest.mark.scenario("""
    Given a definitief Word document, small or large, an Excel or a PowerPoint document, on a zaak in ZAC
    When the behandelaar converts the document to PDF
    Then the document's current version is a PDF/A-2b and PDF/UA with embedded fonts
""")
def test_word_document_is_converted_to_pdf(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    registry: ResourceRegistry,
    suffix: str,
) -> None:
    """A definitief Office document converted in ZAC becomes a PDF/A-2b, PDF/UA with embedded fonts, as ZAC requests."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry, suffix=suffix)
    documents = document_url(urls["zac"], document)
    expect_status(convert_to_pdf(zac, urls["zac"], zaak, document), HTTPStatus.NO_CONTENT, HTTPStatus.OK)
    current = expect_status(zac.get(documents, params={"zaak": str(zaak["uuid"])}), HTTPStatus.OK).json()
    assert current["formaat"] == "application/pdf", current.get("formaat")
    content = expect_status(zac.get(f"{documents}/download"), HTTPStatus.OK).content
    assert content.startswith(b"%PDF")
    assert pdfa_problems(content) == []
