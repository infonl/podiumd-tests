"""KvK through the api-proxy: a company by KvK number, its basisprofiel, and searches.

Ported from TA regression 08, 47, 57, 125 and the KvK parts of 157 and 80. TA called KvK's public
test API directly; QA's api-proxy routes to that API, so the searches use its test set and skip
where the proxy's KvK does not know it (minikube's WireMock). The number and basisprofiel tests
use profile setting kvk_nummer.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import KVK_BASISPROFIELEN
from podiumd_tests.basisregistraties import KVK_HEADERS
from podiumd_tests.basisregistraties import KVK_TEST_ADRES
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.basisregistraties import kvk_zoeken
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("api-proxy")]


@pytest.fixture(scope="module", name="kvk_nummer")
def fixture_kvk_nummer(podiumd_env: Environment) -> str:
    """A KvK number the environment's KvK knows; skips without settings.kvk_nummer."""
    found = podiumd_env.profile.settings.get("kvk_nummer")
    if not found:
        pytest.skip(f"profile {podiumd_env.profile.name} has no settings.kvk_nummer")
    return found


def test_rechtspersoon_by_kvk_nummer(http: requests.Session, urls: dict[str, str], kvk_nummer: str) -> None:
    """Searching by KvK number finds the rechtspersoon with its name (TA reg-47b, reg-57)."""
    params = {"kvkNummer": kvk_nummer, "type": "rechtspersoon"}
    response = expect_status(kvk_zoeken(http, urls["api-proxy"], params), HTTPStatus.OK)
    found = [r for r in entries(response.json()["resultaten"]) if r.get("type") == "rechtspersoon"]
    assert [r["kvkNummer"] for r in found] == [kvk_nummer]
    assert found[0]["naam"]


def test_basisprofiel(http: requests.Session, urls: dict[str, str], kvk_nummer: str) -> None:
    """The basisprofiel of the KvK number answers with that number (TA reg-157c, reg-80)."""
    url = f"{urls['api-proxy']}{KVK_BASISPROFIELEN}/{kvk_nummer}"
    response = expect_status(http.get(url, params={"geoData": "false"}, headers=KVK_HEADERS), HTTPStatus.OK)
    assert response.json()["kvkNummer"] == kvk_nummer


@pytest.fixture(scope="module", name="kvk_test_set")
def fixture_kvk_test_set(http: requests.Session, urls: dict[str, str]) -> None:
    """Skips unless the api-proxy's KvK knows KvK's test set (KvK test API, not a WireMock)."""
    if kvk_zoeken(http, urls["api-proxy"], {"kvkNummer": KVK_TEST_NUMMER}).status_code != HTTPStatus.OK:
        pytest.skip(f"the api-proxy's KvK does not know test company {KVK_TEST_NUMMER} (no KvK test API)")


def resultaten(response: requests.Response) -> list[JsonObject]:
    """The search results of a 200 answer."""
    return entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))


@pytest.mark.usefixtures("kvk_test_set")
def test_search_by_kvk_nummer_finds_rechtspersoon_and_vestigingen(http: requests.Session, urls: dict[str, str]) -> None:
    """A KvK number finds the rechtspersoon and its hoofdvestiging, named Test (TA reg-08, reg-47b)."""
    found = resultaten(kvk_zoeken(http, urls["api-proxy"], {"kvkNummer": KVK_TEST_NUMMER}))
    assert {"rechtspersoon", "hoofdvestiging"} <= {str(r.get("type")) for r in found}
    assert any("test" in str(r.get("naam")).lower() for r in found)


@pytest.mark.usefixtures("kvk_test_set")
@pytest.mark.parametrize(
    "query",
    [{"naam": "Test"}, KVK_TEST_ADRES, {"kvkNummer": KVK_TEST_NUMMER, "naam": "Test"}],
    ids=["naam", "postcode-huisnummer", "kvknummer-naam"],
)
def test_search_finds_the_test_company(http: requests.Session, urls: dict[str, str], query: dict[str, str]) -> None:
    """Searching by name, by address or by number and name finds Test BV Donald (TA reg-47a, reg-47d, reg-125)."""
    found = resultaten(kvk_zoeken(http, urls["api-proxy"], query))
    assert KVK_TEST_NUMMER in {str(r.get("kvkNummer")) for r in found}


@pytest.mark.usefixtures("kvk_test_set")
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


@pytest.mark.usefixtures("kvk_test_set")
def test_postcode_without_huisnummer_is_refused(http: requests.Session, urls: dict[str, str]) -> None:
    """KvK wants postcode and huisnummer together (TA reg-125)."""
    expect_status(kvk_zoeken(http, urls["api-proxy"], {"postcode": KVK_TEST_ADRES["postcode"]}), HTTPStatus.BAD_REQUEST)
