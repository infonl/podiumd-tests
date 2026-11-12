"""ZAC's search: text search, Solr special characters, and the indicaties of the werkvoorraad."""

from __future__ import annotations

import json
import secrets

from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_other_domain_group
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import GERELATEERD
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import csv_export
from podiumd_tests.zac import delete_zoekopdracht
from podiumd_tests.zac import heropenen
from podiumd_tests.zac import koppel_zoekresultaat
from podiumd_tests.zac import opschorten
from podiumd_tests.zac import save_zoekopdracht
from podiumd_tests.zac import search
from podiumd_tests.zac import verlengen
from podiumd_tests.zac import wait_for_indicatie
from podiumd_tests.zac import zac_session
from podiumd_tests.zac import zoekopdrachten
from podiumd_tests.zac_documents import ontkoppel_document
from podiumd_tests.zac_documents import ontkoppelde_documenten_page
from podiumd_tests.zac_documents import uploaded_document

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    # ZAC updates its search index from Open Notificaties' notifications.
    pytest.mark.requires("zac", "openzaak", "keycloak", "opennotificaties"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md,"
        " zoeken-werklijsten-dashboard).",
    ),
]

# ZAC's werklijst of open zaken, for saved zoekopdrachten.
WERKVOORRAAD_ZAKEN = "WERKVOORRAAD_ZAKEN"
# More zaaktypen than fit in Solr's URL as ZAC's filter; ZAC 5.9.1 sends it by POST.
MANY_ZAAKTYPEN = 200
# The characters of Solr's query syntax.
SOLR_SPECIAL = ["+", "-", "&&", "||", "!", "(", ")", "{", "}", "[", "]", "^", '"', "~", "*", "?", ":", "\\", "/"]


@pytest.mark.scenario("""
    Given a zaak in ZAC whose toelichting holds the kenmerk of an Open Formulieren form
    When the behandelaar searches for the kenmerk in all fields and in the toelichting
    Then both searches find the zaak
""")
def test_text_search_finds_the_zaak_by_the_kenmerk_in_its_toelichting(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """ZAC's search for ALLE and ZAAK_TOELICHTING finds a kenmerk such as OF-1A2B3C inside the toelichting."""
    kenmerk = f"OF-{secrets.token_hex(3).upper()}"
    zaak = zac_zaak(toelichting=f"Aanvraag via het formulier met kenmerk {kenmerk}.")

    def is_found_by(veld: str) -> bool:
        found = search(zac, urls["zac"], type="ZAAK", zoeken={veld: kenmerk})
        return any(item.get("id") == zaak["uuid"] for item in entries(found["resultaten"]))

    for veld in ("ALLE", "ZAAK_TOELICHTING"):
        wait_until(partial(is_found_by, veld), timeout=INDEX_TIMEOUT, description=f"{kenmerk} found by {veld}")


@pytest.mark.scenario("""
    Given a behandelaar is logged in to ZAC
    When the behandelaar searches for each character of Solr's query syntax, in all fields and in the omschrijving
    Then ZAC answers every search without an error
""")
def test_solr_special_characters_give_no_error(zac: requests.Session, urls: dict[str, str]) -> None:
    """ZAC escapes the query text: each special character answers 200."""
    failed = []
    for character in SOLR_SPECIAL:
        for veld in ("ALLE", "ZAAK_OMSCHRIJVING"):
            body = {"page": 0, "rows": 1, "type": "ZAAK", "zoeken": {veld: f"a{character}b"}}
            response = zac.put(f"{urls['zac']}/rest/zoeken/list", json=body)
            if response.status_code != HTTPStatus.OK:
                failed.append(f"{veld} {character!r}: {describe(response)}")
    assert not failed, failed


@pytest.mark.scenario("""
    Given two zaken in ZAC
    When the behandelaar searches zaken to relate to the first by the second's zaaknummer with spaces around it
    Then ZAC finds the second zaak
""")
def test_koppel_search_ignores_spaces_around_the_zaaknummer(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """ZAC trims the search text of zaken to link (ZaakKoppelenRestService.buildZoekParameters)."""
    zaak, ander = zac_zaak(), zac_zaak()
    spaced = f"  {ander['identificatie']}  "
    wait_until(
        lambda: koppel_zoekresultaat(zac, urls["zac"], zaak, {**ander, "identificatie": spaced}, GERELATEERD),
        timeout=INDEX_TIMEOUT,
        description=f"{ander['identificatie']} found with spaces around it",
    )


def _opgeschort(zac: requests.Session, zac_url: str, zaak: JsonObject) -> None:
    expect_status(opschorten(zac, zac_url, zaak, 3), HTTPStatus.OK)


def _verlengd(zac: requests.Session, zac_url: str, zaak: JsonObject) -> None:
    zaaktype = section(zaak, "zaaktype")
    if not zaaktype.get("verlengingMogelijk"):
        pytest.skip(f"zaaktype {zaaktype.get('identificatie')} allows no verlenging")
    expect_status(verlengen(zac, zac_url, zaak, 3), HTTPStatus.OK)


def _heropend(zac: requests.Session, zac_url: str, zaak: JsonObject) -> None:
    afronden_intake(zac, zac_url, zaak)
    expect_status(afhandelen(zac, zac_url, zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    expect_status(heropenen(zac, zac_url, zaak), HTTPStatus.OK)


INDICATIES = {"OPSCHORTING": _opgeschort, "VERLENGD": _verlengd, "HEROPEND": _heropend}


@pytest.mark.parametrize("indicatie", list(INDICATIES))
@pytest.mark.scenario("""
    Given an open zaak in ZAC
    When the behandelaar opschort, verlengt, or afhandelt and heropent the zaak
    Then the werkvoorraad lists the zaak with the indicatie opgeschort, verlengd or heropend
""")
def test_werkvoorraad_shows_the_indicatie_of_the_zaak(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], indicatie: str
) -> None:
    """ZAC's search lists the zaak among the open zaken with the indicatie (ZaakIndicatie)."""
    zaak = zac_zaak()
    INDICATIES[indicatie](zac, urls["zac"], zaak)
    wait_for_indicatie(zac, urls["zac"], zaak, indicatie)


@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given a user who is raadpleger on 200 zaaktypen, all of a domain of their own
    When the user opens the werkvoorraad, Mijn zaken and the afgehandelde zaken
    Then ZAC answers each list
""")
def test_werklijsten_work_with_many_zaaktypen(
    podiumd_env: Environment, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """ZAC sends its Solr query with every zaaktype of the user by POST (SearchService.search), not in a URL."""
    group = make_other_domain_group(podiumd_env, registry, "raadpleger", zaaktypen=MANY_ZAAKTYPEN)
    user = zac_session(podiumd_env, *make_group_member(podiumd_env, registry, group))
    for flags in ({"alleenOpenstaandeZaken": True}, {"alleenMijnZaken": True}, {"alleenAfgeslotenZaken": True}):
        search(user, urls["zac"], type="ZAAK", **flags)


def _found_by_kenmerk(zac: requests.Session, zac_url: str, kenmerk: str, count: int, **query: object) -> JsonObject:
    """Wait until ZAC's search for the kenmerk in the toelichting finds count zaken; that search's answer."""

    def found() -> JsonObject | None:
        answer = search(zac, zac_url, type="ZAAK", zoeken={"ZAAK_TOELICHTING": kenmerk}, **query)
        return answer if len(entries(answer["resultaten"])) == count else None

    return wait_until(found, timeout=INDEX_TIMEOUT, description=f"{count} zaken with {kenmerk}")


@pytest.mark.scenario("""
    Given two zaken in ZAC, one openbaar and one vertrouwelijk
    When the behandelaar searches for both
    Then the filter vertrouwelijkheidaanduiding counts one zaak for each value
    When the behandelaar filters on vertrouwelijk
    Then ZAC lists only the vertrouwelijke zaak
""")
def test_vertrouwelijkheidaanduiding_filter_counts_each_value(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """The search's facet ZAAK_VERTROUWELIJKHEIDAANDUIDING lists every value found, and filters on it."""
    kenmerk = f"PT-{secrets.token_hex(4).upper()}"
    zac_zaak(toelichting=kenmerk)
    vertrouwelijk = zac_zaak(toelichting=kenmerk, vertrouwelijkheidaanduiding="vertrouwelijk")
    found = _found_by_kenmerk(zac, urls["zac"], kenmerk, 2)
    facet = entries(section(found, "filters").get("ZAAK_VERTROUWELIJKHEIDAANDUIDING"))
    assert {str(value.get("naam")): value.get("aantal") for value in facet} == {"OPENBAAR": 1, "VERTROUWELIJK": 1}
    filtered = _found_by_kenmerk(
        zac, urls["zac"], kenmerk, 1, filters={"ZAAK_VERTROUWELIJKHEIDAANDUIDING": {"values": ["VERTROUWELIJK"]}}
    )
    assert [item.get("id") for item in entries(filtered["resultaten"])] == [vertrouwelijk["uuid"]]


@pytest.mark.scenario("""
    Given two zaken in ZAC that a search lists
    When the beheerder exports that search to CSV
    Then the export holds the listed zaken in the same order, with their omschrijving
""")
def test_csv_export_holds_the_listed_zaken(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """ZAC's CSV export of a search has a row per listed zaak, in the list's order."""
    kenmerk = f"PT-{secrets.token_hex(4).upper()}"
    zac_zaak(toelichting=kenmerk)
    zac_zaak(toelichting=kenmerk)
    order = {"sorteerVeld": "ZAAK_IDENTIFICATIE", "sorteerRichting": "desc"}
    found = _found_by_kenmerk(zac, urls["zac"], kenmerk, 2, **order)
    listed = [(item.get("identificatie"), item.get("omschrijving")) for item in entries(found["resultaten"])]
    rows = csv_export(zac, urls["zac"], type="ZAAK", zoeken={"ZAAK_TOELICHTING": kenmerk}, **order)
    assert [(row.get("identificatie"), row.get("omschrijving")) for row in rows] == listed


@pytest.mark.scenario("""
    Given the behandelaar's werkvoorraad of zaken
    When the behandelaar saves its search as a zoekopdracht
    Then the werkvoorraad offers the zoekopdracht with its search
    When the behandelaar deletes it
    Then the werkvoorraad no longer offers it
""")
def test_saved_zoekopdracht_is_offered_until_deleted(
    zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """ZAC stores the zoekopdracht per user and werklijst, and gives its search back unchanged."""
    query = {"filters": {"ZAAK_VERTROUWELIJKHEIDAANDUIDING": {"values": ["OPENBAAR"]}}}
    saved = save_zoekopdracht(zac, urls["zac"], registry, WERKVOORRAAD_ZAKEN, query)
    offered = [item for item in zoekopdrachten(zac, urls["zac"], WERKVOORRAAD_ZAKEN) if item.get("id") == saved["id"]]
    assert [(item.get("naam"), json.loads(str(item.get("json")))) for item in offered] == [(saved["naam"], query)]
    delete_zoekopdracht(zac, urls["zac"], saved)
    assert saved["id"] not in {item.get("id") for item in zoekopdrachten(zac, urls["zac"], WERKVOORRAAD_ZAKEN)}


@pytest.mark.scenario("""
    Given a zaak in ZAC with two documents that the behandelaar detached
    When the recordmanager pages through the ontkoppelde documenten of the zaak one per page
    Then each page shows one document with its creatiedatum, and the total of two
""")
def test_ontkoppelde_documenten_are_paged_with_their_creatiedatum(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """maxResults pages ZAC's ontkoppelde documenten; totaal counts all of them."""
    zac_url = urls["zac"]
    zaak = zac_zaak()
    for _ in range(2):
        document = uploaded_document(zac, zac_url, zaak, registry)
        expect_status(
            ontkoppel_document(zac, zac_url, zaak, document, "podiumd-tests", registry), HTTPStatus.NO_CONTENT
        )
    pages = [ontkoppelde_documenten_page(zac, zac_url, zaak, page, 1) for page in (0, 1)]
    shown = [entries(page.get("resultaten")) for page in pages]
    assert [(page.get("totaal"), len(found)) for page, found in zip(pages, shown, strict=True)] == [(2, 1), (2, 1)]
    assert shown[0][0].get("id") != shown[1][0].get("id")
    assert all(found[0].get("creatiedatum") for found in shown), shown
