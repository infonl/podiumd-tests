"""ZAC's companies from the KvK: search, profiles, and a vestiging that is not of the KvK-nummer."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import KVK_ANDERE_VESTIGING
from podiumd_tests.basisregistraties import KVK_TEST_ADRES
from podiumd_tests.basisregistraties import KVK_TEST_HOOFDVESTIGING
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.basisregistraties import KVK_TEST_RSIN
from podiumd_tests.basisregistraties import KVK_TEST_VESTIGING
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac_betrokkenen import wijzig_initiator

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "keycloak"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, betrokkenen-klant).",
    ),
]


@pytest.mark.parametrize(
    ("query", "vestigingsnummer"),
    [
        pytest.param({"kvkNummer": KVK_TEST_NUMMER}, KVK_TEST_VESTIGING, id="kvk-nummer"),
        pytest.param({"rsin": KVK_TEST_RSIN}, None, id="rsin"),
        pytest.param({"vestigingsnummer": KVK_TEST_VESTIGING}, KVK_TEST_VESTIGING, id="vestigingsnummer"),
        pytest.param({"naam": "Test BV Donald"}, KVK_TEST_VESTIGING, id="naam"),
        pytest.param(
            {"postcode": KVK_TEST_ADRES["postcode"], "huisnummer": int(KVK_TEST_ADRES["huisnummer"])},
            KVK_TEST_HOOFDVESTIGING,
            id="postcode-huisnummer",
        ),
    ],
)
@pytest.mark.scenario("""
    Given the KvK test company
    When the behandelaar searches companies by one of its KvK-nummer, RSIN, vestigingsnummer, naam or postcode
    Then ZAC lists the company or its vestiging
""")
def test_bedrijf_is_found_by_each_kvk_field(
    zac: requests.Session, urls: dict[str, str], query: JsonObject, vestigingsnummer: str | None
) -> None:
    """PUT /rest/klanten/bedrijven lists the KvK test company: the rechtspersoon (None) or the vestiging."""
    response = zac.put(f"{urls['zac']}/rest/klanten/bedrijven", json=query)
    found = entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))
    listed = {(bedrijf.get("kvkNummer"), bedrijf.get("vestigingsnummer")) for bedrijf in found}
    assert (KVK_TEST_NUMMER, vestigingsnummer) in listed


@pytest.mark.scenario("""
    Given the KvK test company
    When the behandelaar opens its basisprofiel and the volledig profiel of its hoofdvestiging
    Then both show its RSIN
    And the hoofdvestiging shows its bezoekadres and correspondentieadres
""")
def test_bedrijf_profiles_show_the_rsin_and_addresses(zac: requests.Session, urls: dict[str, str]) -> None:
    """The basisprofiel and the vestigingsprofiel carry the RSIN; the vestigingsprofiel lists both address types."""
    klanten = f"{urls['zac']}/rest/klanten"
    basisprofiel = expect_status(zac.get(f"{klanten}/basisprofiel/{KVK_TEST_NUMMER}"), HTTPStatus.OK).json()
    assert basisprofiel["rsin"] == KVK_TEST_RSIN
    url = f"{klanten}/vestigingsprofiel/{KVK_TEST_HOOFDVESTIGING}"
    profiel = expect_status(zac.get(url), HTTPStatus.OK).json()
    assert (profiel["kvkNummer"], profiel["rsin"]) == (KVK_TEST_NUMMER, KVK_TEST_RSIN)
    adressen = {adres.get("type"): adres.get("postcode") for adres in entries(profiel.get("adressen"))}
    assert adressen.keys() == {"bezoekadres", "correspondentieadres"}
    assert adressen["bezoekadres"] == KVK_TEST_ADRES["postcode"]


@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar makes a vestiging of another company the initiator under the test company's KvK-nummer
    Then the zaak keeps that initiator
    And ZAC finds no vestiging with that vestigingsnummer and KvK-nummer
""")
def test_initiator_with_a_vestiging_of_another_kvk_nummer_is_not_found(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """ZAC stores a mismatching vestiging (it checks the format only); its vestiging lookup answers 404."""
    zaak = zac_zaak()
    zac_url = urls["zac"]
    mismatch = {"type": "VN", "kvkNummer": KVK_TEST_NUMMER, "vestigingsnummer": KVK_ANDERE_VESTIGING}
    expect_status(wijzig_initiator(zac, zac_url, zaak, mismatch, None), HTTPStatus.OK)
    initiator = section(read_zaak(zac, zac_url, str(zaak["uuid"])), "initiatorIdentificatie")
    assert (initiator.get("kvkNummer"), initiator.get("vestigingsnummer")) == (KVK_TEST_NUMMER, KVK_ANDERE_VESTIGING)
    lookup = zac.get(f"{zac_url}/rest/klanten/vestiging/{KVK_ANDERE_VESTIGING}/{KVK_TEST_NUMMER}")
    expect_status(lookup, HTTPStatus.NOT_FOUND)
