"""BRP personen through the api-proxy: lookups, searches and refused queries.

Ported from TA regression 07, 40, 11 and the BRP parts of 80, 119, 121 and 150. The BSNs are from the
BRP test set that the personen mock serves.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import BRP_PERSONEN
from podiumd_tests.basisregistraties import brp_personen
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Mapping

    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("api-proxy")]

EREBOS = "999990019"
KIERKEGAARD = "999990020"
NAAM = ["burgerservicenummer", "naam.voornamen", "naam.geslachtsnaam"]


def personen(http: requests.Session, urls: dict[str, str], query: Mapping[str, object]) -> list[JsonObject]:
    """The personen a query finds; it must answer 200 with the query's type."""
    body = expect_status(brp_personen(http, urls["api-proxy"], query), HTTPStatus.OK).json()
    assert body["type"] == query["type"]
    return entries(body["personen"])


def test_person_by_bsn(http: requests.Session, urls: dict[str, str]) -> None:
    """A test-set BSN gives that person with a name (TA reg-07, reg-11)."""
    found = personen(
        http, urls, {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [EREBOS], "fields": NAAM}
    )
    assert [(p["burgerservicenummer"], p["naam"]) for p in found] == [
        (EREBOS, {"voornamen": "Erebos", "geslachtsnaam": "Bultenaar"})
    ]


def test_unknown_bsn_finds_no_one(http: requests.Session, urls: dict[str, str]) -> None:
    """A BSN outside the test set gives an empty list, not an error (TA reg-07)."""
    query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": ["123456789"], "fields": NAAM[:1]}
    assert personen(http, urls, query) == []


def test_several_bsns_at_once(http: requests.Session, urls: dict[str, str]) -> None:
    """One query returns every known BSN it asks for (TA reg-40d)."""
    query = {
        "type": "RaadpleegMetBurgerservicenummer",
        "burgerservicenummer": [EREBOS, KIERKEGAARD],
        "fields": NAAM[:1],
    }
    assert {p["burgerservicenummer"] for p in personen(http, urls, query)} == {EREBOS, KIERKEGAARD}


@pytest.mark.parametrize(
    ("geslachtsnaam", "geboortedatum", "expected"),
    [("Kierkegaard", "1931-07-06", [KIERKEGAARD]), ("Janssen", "1900-01-01", [])],
)
def test_search_by_name_and_birth_date(
    http: requests.Session, urls: dict[str, str], geslachtsnaam: str, geboortedatum: str, expected: list[str]
) -> None:
    """Searching by surname and birth date finds exactly the matching people (TA reg-40a, 40b)."""
    query = {
        "type": "ZoekMetGeslachtsnaamEnGeboortedatum",
        "geslachtsnaam": geslachtsnaam,
        "geboortedatum": geboortedatum,
        "fields": NAAM[:1],
    }
    assert [p["burgerservicenummer"] for p in personen(http, urls, query)] == expected


def test_search_by_postcode_and_huisnummer(http: requests.Session, urls: dict[str, str]) -> None:
    """Searching by postcode and huisnummer finds the residents of that address, and no one at an unknown one (TA reg-119)."""
    query = {"type": "ZoekMetPostcodeEnHuisnummer", "fields": NAAM[:1]}
    erebos = personen(http, urls, {**query, "postcode": "3224TT", "huisnummer": 4})
    assert EREBOS in [p["burgerservicenummer"] for p in erebos]
    assert personen(http, urls, {**query, "postcode": "1234AB", "huisnummer": 1}) == []


@pytest.mark.parametrize(
    "query",
    [{}, {"type": "OnbekendType"}, {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": ["abc"]}],
    ids=["empty", "unknown-type", "invalid-bsn"],
)
def test_invalid_query_is_refused(http: requests.Session, urls: dict[str, str], query: Mapping[str, object]) -> None:
    """An invalid query answers 400 or 422, never 5xx (TA reg-40c, reg-80, reg-121)."""
    response = brp_personen(http, urls["api-proxy"], query)
    expect_status(response, HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY)


def test_bsn_failing_the_eleven_test_finds_no_one(http: requests.Session, urls: dict[str, str]) -> None:
    """A BSN that fails the eleven-test is refused, or finds no one; never 5xx (TA reg-150)."""
    query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": ["123456789"]}
    response = brp_personen(http, urls["api-proxy"], {**query, "fields": ["burgerservicenummer"]})
    expect_status(response, HTTPStatus.OK, HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY)
    if response.status_code == HTTPStatus.OK:
        assert response.json()["personen"] == []


def test_v1_lookup_is_not_offered(http: requests.Session, urls: dict[str, str]) -> None:
    """The BRP serves Haal Centraal V2 only: the V1 path answers 405 (TA reg-11, finding 14)."""
    v1 = urls["api-proxy"] + BRP_PERSONEN.replace("personen", f"ingeschrevenpersonen/{EREBOS}")
    expect_status(http.get(v1), HTTPStatus.METHOD_NOT_ALLOWED)
