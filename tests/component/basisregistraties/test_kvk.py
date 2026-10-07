"""KvK through the api-proxy: a company by KvK number, and its basisprofiel.

Ported from TA regression 47b, 57 and the basisprofiel parts of 157 and 80. Searches by name or
postcode (08, 47a/c/d, 125, 80) need the KvK test set; minikube's WireMock serves fixed mappings
only, so the KvK number comes from profile setting kvk_nummer.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import KVK_BASISPROFIELEN
from podiumd_tests.basisregistraties import KVK_HEADERS
from podiumd_tests.basisregistraties import KVK_ZOEKEN
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment

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
    response = expect_status(
        http.get(urls["api-proxy"] + KVK_ZOEKEN, params=params, headers=KVK_HEADERS), HTTPStatus.OK
    )
    found = [r for r in entries(response.json()["resultaten"]) if r.get("type") == "rechtspersoon"]
    assert [r["kvkNummer"] for r in found] == [kvk_nummer]
    assert found[0]["naam"]


def test_basisprofiel(http: requests.Session, urls: dict[str, str], kvk_nummer: str) -> None:
    """The basisprofiel of the KvK number answers with that number (TA reg-157c, reg-80)."""
    url = f"{urls['api-proxy']}{KVK_BASISPROFIELEN}/{kvk_nummer}"
    response = expect_status(http.get(url, params={"geoData": "false"}, headers=KVK_HEADERS), HTTPStatus.OK)
    assert response.json()["kvkNummer"] == kvk_nummer
