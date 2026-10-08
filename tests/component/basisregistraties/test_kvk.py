"""KvK through the api-proxy, against KvK's test API and its test set (Test BV Donald).

Ported from TA regression 08, 47, 57, 125 and the KvK parts of 157 and 80. TA called KvK's test
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


def resultaten(response: requests.Response) -> list[JsonObject]:
    """The search results of a 200 answer."""
    return entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))


def test_search_by_kvk_nummer_finds_rechtspersoon_and_vestigingen(http: requests.Session, urls: dict[str, str]) -> None:
    """A KvK number finds the rechtspersoon and its hoofdvestiging, named Test (TA reg-08, reg-47b, reg-57)."""
    found = resultaten(kvk_zoeken(http, urls["api-proxy"], {"kvkNummer": KVK_TEST_NUMMER}))
    assert {"rechtspersoon", "hoofdvestiging"} <= {str(r.get("type")) for r in found}
    assert any("test" in str(r.get("naam")).lower() for r in found)


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
def test_search_finds_the_test_company(http: requests.Session, urls: dict[str, str], query: dict[str, str]) -> None:
    """Searching by name, by address or by number and name finds Test BV Donald (TA reg-47a, reg-47d, reg-125)."""
    found = resultaten(kvk_zoeken(http, urls["api-proxy"], query))
    assert KVK_TEST_NUMMER in {str(r.get("kvkNummer")) for r in found}


@pytest.mark.parametrize(
    "query",
    [{"kvkNummer": "00000000"}, {"postcode": "9999XX", "huisnummer": "999"}],
    ids=["kvknummer", "postcode-huisnummer"],
)
def test_search_without_match_finds_nothing(
    http: requests.Session, urls: dict[str, str], query: dict[str, str]
) -> None:
    """An unknown number or address gives 404, or 200 without results (TA reg-08, reg-47c, reg-125)."""
    response = kvk_zoeken(http, urls["api-proxy"], query)
    if response.status_code != HTTPStatus.NOT_FOUND:
        assert resultaten(response) == []


def test_postcode_without_huisnummer_is_refused(http: requests.Session, urls: dict[str, str]) -> None:
    """KvK wants postcode and huisnummer together (TA reg-125)."""
    expect_status(kvk_zoeken(http, urls["api-proxy"], {"postcode": KVK_TEST_ADRES["postcode"]}), HTTPStatus.BAD_REQUEST)


def test_basisprofiel(http: requests.Session, urls: dict[str, str]) -> None:
    """The basisprofiel of the test company answers with its number (TA reg-157c, reg-80)."""
    response = expect_status(kvk_basisprofiel(http, urls["api-proxy"], KVK_TEST_NUMMER), HTTPStatus.OK)
    assert response.json()["kvkNummer"] == KVK_TEST_NUMMER
