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


POSTCODE = "ZoekMetPostcodeEnHuisnummer"
NAAM = "ZoekMetGeslachtsnaamEnGeboortedatum"
# Persons of the BRP test set that KISS's own scenarios search.
MELAP = "999994098"  # Julia Christine Maria Melap, born 1946-09-12, as is Melapatti
KRABBEN = "999998912"  # Koosje Krabben, one of 11 persons at 2511CA 21, 6 of them Kornelissen
KORNELISSEN = "999998900"
GOEDMUT = "999992995"  # Jan Goedmut, at 1074HK 1 B with one other of the 4 persons at 1074HK 1


@pytest.mark.parametrize(
    ("query", "expected", "count"),
    [
        pytest.param({"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [EREBOS]}, EREBOS, 1, id="bsn"),
        pytest.param(
            {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": ["123456789"]},
            None,
            0,
            id="bsn-unknown",
        ),
        pytest.param(
            {"type": NAAM, "geslachtsnaam": "Kierkegaard", "geboortedatum": "1931-07-06"},
            KIERKEGAARD,
            1,
            id="naam-geboortedatum",
        ),
        pytest.param(
            {"type": NAAM, "geslachtsnaam": "Janssen", "geboortedatum": "1900-01-01"},
            None,
            0,
            id="naam-geboortedatum-unknown",
        ),
        pytest.param(
            {"type": NAAM, "geslachtsnaam": "Mel*", "geboortedatum": "1946-09-12"},
            MELAP,
            2,
            id="naam-deel-geboortedatum",
        ),
        pytest.param({"type": POSTCODE, "postcode": "3224TT", "huisnummer": 4}, EREBOS, 4, id="postcode"),
        pytest.param({"type": POSTCODE, "postcode": "1234AB", "huisnummer": 1}, None, 0, id="postcode-unknown"),
        pytest.param({"type": POSTCODE, "postcode": "2511CA", "huisnummer": 21}, KRABBEN, 11, id="postcode-several"),
        pytest.param(
            {"type": POSTCODE, "postcode": "2511CA", "huisnummer": 21, "geslachtsnaam": "Krabben*"},
            KRABBEN,
            3,
            id="postcode-achternaam",
        ),
        pytest.param(
            {"type": POSTCODE, "postcode": "2511CA", "huisnummer": 21, "geslachtsnaam": "Kor*"},
            KORNELISSEN,
            6,
            id="postcode-deel-achternaam",
        ),
        pytest.param(
            {"type": POSTCODE, "postcode": "1074HK", "huisnummer": 1, "huisletter": "b"},
            GOEDMUT,
            2,
            id="postcode-huisletter",
        ),
    ],
)
@pytest.mark.source(
    f"{E2E}/SearchPersonScenarios.cs",
    "Searching a person by BSN, by (part of the) last name and date of birth, and by postcode and huisnummer,"
    " filtered on (part of the) last name or huisletter; found and not found.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    When the medewerker searches the BRP by BSN, by (part of the) geslachtsnaam and geboortedatum, or by address
    And narrows an address search by (part of the) geslachtsnaam or huisletter
    Then KISS finds exactly the persons of the BRP test set that match
    And finds no one for search terms outside the test set
""")
def test_person_search(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    query: dict[str, object],
    expected: str | None,
    count: int,
) -> None:
    """KISS's BRP search finds the number of test-set persons, the expected one among them.

    KISS rewrites the body and keeps its Content-Length, so the JSON is compact, as KISS's frontend sends it.
    """
    body = json.dumps({**query, "fields": ["burgerservicenummer"]}, separators=(",", ":"))
    found = kiss_session(KCC).post(
        f"{urls['kiss']}/api/haalcentraal/brp/personen", data=body, headers={"Content-Type": "application/json"}
    )
    bsns = [str(p.get("burgerservicenummer")) for p in entries(expect_status(found, HTTPStatus.OK).json()["personen"])]
    assert len(bsns) == count, bsns
    assert expected is None or expected in bsns


# A KvK test-set address with several vestigingen of another company (90004051).
KVK_SEVERAL_ADRES = {"postcode": "2352SZ", "huisnummer": "37"}


@pytest.mark.parametrize(
    ("query", "kvk_nummer", "minimum"),
    [
        pytest.param({"kvkNummer": KVK_TEST_NUMMER}, KVK_TEST_NUMMER, 2, id="kvknummer-several"),
        pytest.param({"kvkNummer": "12345678"}, None, 0, id="kvknummer-unknown"),
        pytest.param({"naam": "Test"}, KVK_TEST_NUMMER, 1, id="naam"),
        pytest.param({"naam": "Donald"}, KVK_TEST_NUMMER, 2, id="naam-several"),
        pytest.param({"naam": "test automation"}, None, 0, id="naam-unknown"),
        pytest.param(
            {"vestigingsnummer": BEDRIJF.attributes["vestigingsnummer"][0]}, KVK_TEST_NUMMER, 1, id="vestigingsnummer"
        ),
        pytest.param(KVK_TEST_ADRES, KVK_TEST_NUMMER, 1, id="postcode-huisnummer"),
        pytest.param(KVK_SEVERAL_ADRES, "90004051", 2, id="postcode-huisnummer-several"),
        pytest.param({"postcode": "1234AB", "huisnummer": "10"}, None, 0, id="postcode-huisnummer-unknown"),
    ],
)
@pytest.mark.source(
    f"{E2E}/SearchCompanyScenarios.cs",
    "Searching a company by name, by KvK number, by vestigingsnummer and by postcode and huisnummer, with one or"
    " several results; found and not found.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    When the medewerker searches KvK by KvK number, naam, vestigingsnummer, or postcode and huisnummer
    Then KISS finds the company of the KvK test set, with each of its results where there are several
    And finds nothing for an unknown KvK number, naam or address
""")
def test_company_search(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    query: dict[str, str],
    kvk_nummer: str | None,
    minimum: int,
) -> None:
    """KISS's KvK search gives at least the minimum of results of the KvK number, or nothing (404 or no results)."""
    response = kiss_session(KCC).get(f"{urls['kiss']}/api/kvk/v2/zoeken", params=query)
    if kvk_nummer is None and response.status_code == HTTPStatus.NOT_FOUND:
        return
    numbers = [
        str(r.get("kvkNummer")) for r in entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))
    ]
    if kvk_nummer is None:
        assert numbers == []
    else:
        assert numbers.count(kvk_nummer) >= minimum, numbers
