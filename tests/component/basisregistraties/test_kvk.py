"""KvK through the api-proxy, against KvK's test API and its test set (Test BV Donald).

Ported from TA regression 08, 47, 57, 125 and the KvK parts of 80, 150 and 157. TA called KvK's test
API directly; here the requests go through the api-proxy, which routes there on every estate.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import KVK_TEST_ADRES
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.basisregistraties import kvk_basisprofiel
from podiumd_tests.basisregistraties import kvk_zoeken
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

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


def resultaten(response: requests.Response) -> list[JsonObject]:
    """The search results of a 200 answer."""
    return entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))


@REG_08
@REG_47
@REG_57
def test_search_by_kvk_nummer_finds_rechtspersoon_and_vestigingen(http: requests.Session, urls: dict[str, str]) -> None:
    """A KvK number finds the rechtspersoon and its hoofdvestiging, named Test (TA reg-08, reg-47b, reg-57)."""
    found = resultaten(kvk_zoeken(http, urls["api-proxy"], {"kvkNummer": KVK_TEST_NUMMER}))
    assert {"rechtspersoon", "hoofdvestiging"} <= {str(r.get("type")) for r in found}
    assert any("test" in str(r.get("naam")).lower() for r in found)


@REG_47
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
def test_search_without_match_finds_nothing(
    http: requests.Session, urls: dict[str, str], query: dict[str, str]
) -> None:
    """An unknown number or address gives 404, or 200 without results (TA reg-08, reg-47c, reg-125)."""
    response = kvk_zoeken(http, urls["api-proxy"], query)
    if response.status_code != HTTPStatus.NOT_FOUND:
        assert resultaten(response) == []


@pytest.mark.parametrize("nummer", ["ABCDEFGH", "1234"], ids=["letters", "too-short"])
@REG_150
def test_invalid_kvk_nummer_is_refused(http: requests.Session, urls: dict[str, str], nummer: str) -> None:
    """A KvK number that is not 8 digits answers 400 (TA reg-150)."""
    expect_status(kvk_zoeken(http, urls["api-proxy"], {"kvkNummer": nummer}), HTTPStatus.BAD_REQUEST)


@REG_125
def test_postcode_without_huisnummer_is_refused(http: requests.Session, urls: dict[str, str]) -> None:
    """KvK wants postcode and huisnummer together (TA reg-125)."""
    expect_status(kvk_zoeken(http, urls["api-proxy"], {"postcode": KVK_TEST_ADRES["postcode"]}), HTTPStatus.BAD_REQUEST)


@pytest.mark.tc("INT-004", "INT-005")
@REG_157
@REG_80
def test_basisprofiel(http: requests.Session, urls: dict[str, str]) -> None:
    """The basisprofiel of the test company answers with its number (TA reg-157c, reg-80)."""
    response = expect_status(kvk_basisprofiel(http, urls["api-proxy"], KVK_TEST_NUMMER), HTTPStatus.OK)
    assert response.json()["kvkNummer"] == KVK_TEST_NUMMER
