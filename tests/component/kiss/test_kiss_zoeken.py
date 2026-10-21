"""KISS's person and company search, through its own BRP and KvK proxies, found and not found.

Ported from KISS's Playwright suite (Kiss.Bff.EndToEndTest/ContactMomentSearch), as the BFF calls of its search
page. The api-proxy itself is tested in tests/component/basisregistraties.
"""

from __future__ import annotations

import json

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KIERKEGAARD
from podiumd_tests.basisregistraties import KVK_TEST_ADRES
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.bootstrap.keycloak import KeycloakUser

pytestmark = [pytest.mark.component, pytest.mark.requires("kiss", "keycloak")]

E2E = "upstream klantinteractie-servicesysteem/KISS-frontend Kiss.Bff.EndToEndTest/ContactMomentSearch"
_, _, BEDRIJF = IDENTITIES


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        pytest.param({"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [EREBOS]}, EREBOS, id="bsn"),
        pytest.param(
            {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": ["123456789"]}, None, id="bsn-unknown"
        ),
        pytest.param(
            {
                "type": "ZoekMetGeslachtsnaamEnGeboortedatum",
                "geslachtsnaam": "Kierkegaard",
                "geboortedatum": "1931-07-06",
            },
            KIERKEGAARD,
            id="naam-geboortedatum",
        ),
        pytest.param(
            {"type": "ZoekMetGeslachtsnaamEnGeboortedatum", "geslachtsnaam": "Janssen", "geboortedatum": "1900-01-01"},
            None,
            id="naam-geboortedatum-unknown",
        ),
        pytest.param(
            {"type": "ZoekMetPostcodeEnHuisnummer", "postcode": "3224TT", "huisnummer": 4}, EREBOS, id="postcode"
        ),
        pytest.param(
            {"type": "ZoekMetPostcodeEnHuisnummer", "postcode": "1234AB", "huisnummer": 1},
            None,
            id="postcode-unknown",
        ),
    ],
)
@pytest.mark.source(
    f"{E2E}/SearchPersonScenarios.cs",
    "Searching a person by BSN, by last name and date of birth, and by postcode and huisnummer; found and not found.",
)
def test_person_search(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    query: dict[str, object],
    expected: str | None,
) -> None:
    """KISS's BRP search finds the test-set person, or no one for an unknown one.

    KISS rewrites the body and keeps its Content-Length, so the JSON is compact, as KISS's frontend sends it.
    """
    body = json.dumps({**query, "fields": ["burgerservicenummer"]}, separators=(",", ":"))
    found = kiss_session(KCC).post(
        urls["kiss"] + "/api/haalcentraal/brp/personen", data=body, headers={"Content-Type": "application/json"}
    )
    bsns = [str(p.get("burgerservicenummer")) for p in entries(expect_status(found, HTTPStatus.OK).json()["personen"])]
    assert (expected in bsns) if expected else bsns == []


@pytest.mark.parametrize(
    ("query", "found"),
    [
        pytest.param({"kvkNummer": KVK_TEST_NUMMER}, True, id="kvknummer"),
        pytest.param({"kvkNummer": "12345678"}, False, id="kvknummer-unknown"),
        pytest.param({"naam": "Test"}, True, id="naam"),
        pytest.param({"vestigingsnummer": BEDRIJF.attributes["vestigingsnummer"][0]}, True, id="vestigingsnummer"),
        pytest.param(KVK_TEST_ADRES, True, id="postcode-huisnummer"),
    ],
)
@pytest.mark.source(
    f"{E2E}/SearchCompanyScenarios.cs",
    "Searching a company by name, by KvK number and by vestigingsnummer; found and not found.",
)
def test_company_search(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    query: dict[str, str],
    found: bool,  # noqa: FBT001  # a parameter
) -> None:
    """KISS's KvK search finds the KvK test company, or nothing for an unknown number (404 or no results)."""
    response = kiss_session(KCC).get(urls["kiss"] + "/api/kvk/v2/zoeken", params=query)
    if not found and response.status_code == HTTPStatus.NOT_FOUND:
        return
    numbers = {
        str(r.get("kvkNummer")) for r in entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))
    }
    assert (KVK_TEST_NUMMER in numbers) == found, numbers
