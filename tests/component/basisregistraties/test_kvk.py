"""KvK through the api-proxy, against KvK's test API and its test set (Test BV Donald, one company per rechtsvorm).

Ported from TA regression 08, 47, 57, 125 and the KvK parts of 80, 150 and 157. TA called KvK's test
API directly; here the requests go through the api-proxy, which routes there on every estate.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import KVK_FOUTMELDINGEN
from podiumd_tests.basisregistraties import KVK_GEEN_PRODUCT
from podiumd_tests.basisregistraties import KVK_GEEN_RESULTATEN
from podiumd_tests.basisregistraties import KVK_RECHTSVORMEN
from podiumd_tests.basisregistraties import KVK_TEST_ADRES
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.basisregistraties import kvk_basisprofiel
from podiumd_tests.basisregistraties import kvk_foutcodes
from podiumd_tests.basisregistraties import kvk_zoeken
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.basisregistraties import KvkBedrijf
    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("api-proxy")]

REG_08 = pytest.mark.source(
    "TA regression/08-kvk-bedrijf-zoeken.spec.ts",
    "Checks KvK's test API is reachable and finds the test companies by KvK number.",
)
REG_47 = pytest.mark.source(
    "TA regression/47-kvk-edge-cases.spec.ts",
    "Covers KvK edge cases: search by trade name, filter by type, an unknown number, the detail call.",
)
REG_57 = pytest.mark.source(
    "TA regression/57-kvk-prefill.spec.ts", "Checks the KvK API returns the company fields Open Formulieren prefills."
)
REG_80 = pytest.mark.source(
    "TA regression/80-brp-kvk-prefill-foutpaden.spec.ts",
    "Covers BRP and KvK prefill error paths and alternative searches, such as by name.",
)
REG_125 = pytest.mark.source(
    "TA regression/125-kvk-postcode-huisnummer-zoek.spec.ts",
    "Covers KvK search by postcode and huisnummer, which KISS uses when the KCC employee has no KvK number.",
)
REG_150 = pytest.mark.source(
    "TA regression/150-of-prefill-foutpaden.spec.ts",
    "Checks that BRP and KvK calls fail gracefully on invalid input: a 4xx, never a 500.",
)
REG_157 = pytest.mark.source(
    "TA regression/157-contact-haalcentraal-validatie.spec.ts",
    "Checks that a company unknown to Contact can be found through KvK.",
)
KVK_TESTSET = pytest.mark.source(
    "external developers.kvk.nl documentation/testing",
    "KvK's test set has a KvK-nummer per rechtsvorm, and two KvK-nummers that answer an error.",
)


def resultaten(response: requests.Response) -> list[JsonObject]:
    """The search results of a 200 answer."""
    return entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))


@REG_08
@REG_47
@REG_57
@pytest.mark.scenario("""
    Given the test company in KvK's test set
    When KvK is searched by its KvK number through the api-proxy
    Then the results hold its rechtspersoon and its hoofdvestiging
    And a result is named Test
""")
def test_search_by_kvk_nummer_finds_rechtspersoon_and_vestigingen(http: requests.Session, urls: dict[str, str]) -> None:
    """A KvK number finds the rechtspersoon and its hoofdvestiging, named Test (TA reg-08, reg-47b, reg-57)."""
    found = resultaten(kvk_zoeken(http, urls["api-proxy"], {"kvkNummer": KVK_TEST_NUMMER}))
    assert {"rechtspersoon", "hoofdvestiging"} <= {str(r.get("type")) for r in found}
    assert any("test" in str(r.get("naam")).lower() for r in found)


@REG_47
@pytest.mark.scenario("""
    Given the test company in KvK's test set
    When KvK is searched by its KvK number for type rechtspersoon only
    Then every result is a rechtspersoon
""")
def test_search_by_type_finds_only_that_type(http: requests.Session, urls: dict[str, str]) -> None:
    """type=rechtspersoon leaves out the vestigingen (TA reg-47b)."""
    query = {"kvkNummer": KVK_TEST_NUMMER, "type": "rechtspersoon"}
    found = resultaten(kvk_zoeken(http, urls["api-proxy"], query))
    assert {str(r.get("type")) for r in found} == {"rechtspersoon"}


@pytest.mark.parametrize(
    "query",
    [{"naam": "Test"}, KVK_TEST_ADRES, {"kvkNummer": KVK_TEST_NUMMER, "naam": "Test"}],
    ids=["naam", "postcode-huisnummer", "kvknummer-naam"],
)
@pytest.mark.tc("INT-005")
@REG_47
@REG_125
@pytest.mark.scenario("""
    Given the test company in KvK's test set
    When KvK is searched through the api-proxy by name, by postcode and huisnummer, or by KvK number and name
    Then the test company is among the results
""")
def test_search_finds_the_test_company(http: requests.Session, urls: dict[str, str], query: dict[str, str]) -> None:
    """Searching by name, by address or by number and name finds Test BV Donald (TA reg-47a, reg-47d, reg-125)."""
    found = resultaten(kvk_zoeken(http, urls["api-proxy"], query))
    assert KVK_TEST_NUMMER in {str(r.get("kvkNummer")) for r in found}


@pytest.mark.parametrize(
    "query",
    [{"kvkNummer": "00000000"}, {"postcode": "9999XX", "huisnummer": "999"}],
    ids=["kvknummer", "postcode-huisnummer"],
)
@REG_08
@REG_47
@REG_125
@pytest.mark.scenario("""
    Given a KvK number or an adres that KvK does not know
    When KvK is searched by it through the api-proxy
    Then KvK answers 404, or 200 without results
""")
def test_search_without_match_finds_nothing(
    http: requests.Session, urls: dict[str, str], query: dict[str, str]
) -> None:
    """An unknown number or address gives 404, or 200 without results (TA reg-08, reg-47c, reg-125)."""
    response = kvk_zoeken(http, urls["api-proxy"], query)
    if response.status_code != HTTPStatus.NOT_FOUND:
        assert resultaten(response) == []


@pytest.mark.parametrize("nummer", ["ABCDEFGH", "1234"], ids=["letters", "too-short"])
@REG_150
@pytest.mark.scenario("""
    Given a KvK number that is not 8 digits
    When KvK is searched by it through the api-proxy
    Then KvK refuses it with 400
""")
def test_invalid_kvk_nummer_is_refused(http: requests.Session, urls: dict[str, str], nummer: str) -> None:
    """A KvK number that is not 8 digits answers 400 (TA reg-150)."""
    expect_status(kvk_zoeken(http, urls["api-proxy"], {"kvkNummer": nummer}), HTTPStatus.BAD_REQUEST)


@REG_125
@pytest.mark.scenario("""
    When KvK is searched by a postcode without huisnummer through the api-proxy
    Then KvK refuses it with 400
""")
def test_postcode_without_huisnummer_is_refused(http: requests.Session, urls: dict[str, str]) -> None:
    """KvK wants postcode and huisnummer together (TA reg-125)."""
    expect_status(kvk_zoeken(http, urls["api-proxy"], {"postcode": KVK_TEST_ADRES["postcode"]}), HTTPStatus.BAD_REQUEST)


@pytest.mark.parametrize("bedrijf", KVK_RECHTSVORMEN.values(), ids=list(KVK_RECHTSVORMEN))
@pytest.mark.tc("INT-004", "INT-005")
@REG_157
@REG_80
@KVK_TESTSET
@pytest.mark.scenario("""
    Given a company of KvK's test set of each rechtsvorm
    When its basisprofiel is requested through the api-proxy
    Then KvK gives the basisprofiel with its KvK number and naam
    And its eigenaar has that rechtsvorm
""")
def test_basisprofiel(http: requests.Session, urls: dict[str, str], bedrijf: KvkBedrijf) -> None:
    """The basisprofiel carries the company's KvK number, naam and rechtsvorm (TA reg-157c, reg-80)."""
    profiel = expect_status(kvk_basisprofiel(http, urls["api-proxy"], bedrijf.kvk_nummer), HTTPStatus.OK).json()
    eigenaar = section(section(profiel, "_embedded"), "eigenaar")
    assert (profiel["kvkNummer"], profiel["naam"], eigenaar.get("rechtsvorm")) == bedrijf


@pytest.mark.parametrize("nummer", KVK_FOUTMELDINGEN)
@KVK_TESTSET
@pytest.mark.scenario("""
    Given a KvK number of KvK's test set that answers an error
    When its basisprofiel is requested through the api-proxy
    Then KvK answers 404 with the fout code that it cannot deliver the product
    When KvK is searched by that number
    Then KvK answers 404 with the fout code that it found nothing
""")
def test_foutmelding_numbers_answer_404_with_a_fout_code(
    http: requests.Session, urls: dict[str, str], nummer: str
) -> None:
    """The error numbers answer 404 with IPD0005 (basisprofiel) and IPD5200 (zoeken), never 5xx."""
    profiel = expect_status(kvk_basisprofiel(http, urls["api-proxy"], nummer), HTTPStatus.NOT_FOUND)
    assert kvk_foutcodes(profiel) == {KVK_GEEN_PRODUCT}
    zoeken = expect_status(kvk_zoeken(http, urls["api-proxy"], {"kvkNummer": nummer}), HTTPStatus.NOT_FOUND)
    assert kvk_foutcodes(zoeken) == {KVK_GEEN_RESULTATEN}
