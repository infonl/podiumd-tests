"""ZAC's search: text search, Solr special characters, and the indicaties of the werkvoorraad."""

from __future__ import annotations

import secrets

from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import heropenen
from podiumd_tests.zac import opschorten
from podiumd_tests.zac import search
from podiumd_tests.zac import verlengen
from podiumd_tests.zac import wait_for_indicatie

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

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
