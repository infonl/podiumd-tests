"""BRP personen through the api-proxy: lookups, searches and refused queries.

Ported from TA regression 07, 40, 11 and the BRP parts of 80, 119, 121 and 150. The BSNs are from the
BRP test set that the personen mock serves.
"""

from __future__ import annotations

from http import HTTPStatus
from itertools import repeat
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import BRP_PERSONEN
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KIERKEGAARD
from podiumd_tests.basisregistraties import brp_gevonden
from podiumd_tests.basisregistraties import brp_personen
from podiumd_tests.basisregistraties import brp_persoon
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Mapping

    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("api-proxy")]

REG_07 = pytest.mark.source(
    "TA regression/07-brp-persoon-zoeken.spec.ts",
    "Checks the BRP implements the Haal Centraal lookup by BSN, as KISS's person search uses it.",
)
REG_11 = pytest.mark.source(
    "TA regression/11-of-brp-prefill.spec.ts",
    "Documents that Open Formulieren's BRP prefill calls Haal Centraal V1 while the BRP serves V2 only.",
)
REG_40 = pytest.mark.source(
    "TA regression/40-brp-zoek-criteria.spec.ts",
    "Covers the other BRP searches KISS uses: surname and birth date, several BSNs, an invalid BSN.",
)
REG_80 = pytest.mark.source(
    "TA regression/80-brp-kvk-prefill-foutpaden.spec.ts",
    "Covers BRP and KvK prefill error paths: malformed BSN or KvK number, empty parameters.",
)
REG_119 = pytest.mark.source(
    "TA regression/119-infra-quick-wins.spec.ts",
    "Covers BRP search by postcode and huisnummer, and an anonymous requester who is not in the BRP.",
)
REG_121 = pytest.mark.source(
    "TA regression/121-continuiteit-graceful-degradation.spec.ts",
    "Checks a component answers a clean error, not a crash or a hang, when its upstream fails.",
)
BRP_FEATURES = pytest.mark.source(
    "external BRP-API/Haal-Centraal-BRP-bevragen features/bevragen/*fout-cases.feature, features/input-validatie",
    "The BRP API refuses an invalid query with 400 and names each invalid parameter and the rule it breaks.",
)
BRP_ADRESSERING = pytest.mark.source(
    "external BRP-API/Haal-Centraal-BRP-bevragen features/bevragen/persoon/adressering",
    "The BRP API derives a person's full name, age and address lines (aanhef, aanschrijfwijze, adresregels).",
)
REG_150 = pytest.mark.source(
    "TA regression/150-of-prefill-foutpaden.spec.ts",
    "Checks that BRP and KvK calls fail gracefully on invalid input: a 4xx, never a 500.",
)


NAAM = ["burgerservicenummer", "naam.voornamen", "naam.geslachtsnaam"]
RAADPLEEG_EREBOS = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [EREBOS]}
# The most BSNs one query may ask for.
MAX_BSNS = 20


@REG_07
@REG_11
@pytest.mark.scenario("""
    Given a person in the BRP test set
    When the person is looked up by BSN through the api-proxy
    Then the BRP gives exactly that person with voornamen and geslachtsnaam
""")
def test_person_by_bsn(http: requests.Session, urls: dict[str, str]) -> None:
    """A test-set BSN gives that person with a name (TA reg-07, reg-11)."""
    found = brp_persoon(http, urls["api-proxy"], EREBOS, NAAM)
    assert (found["burgerservicenummer"], found["naam"]) == (
        EREBOS,
        {"voornamen": "Erebos", "geslachtsnaam": "Bultenaar"},
    )


@REG_07
@REG_119
@pytest.mark.scenario("""
    Given a BSN that is not in the BRP test set
    When it is looked up through the api-proxy
    Then the BRP answers with an empty list, not an error
""")
def test_unknown_bsn_finds_no_one(http: requests.Session, urls: dict[str, str]) -> None:
    """A BSN outside the test set gives an empty list, not an error (TA reg-07)."""
    query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": ["123456789"], "fields": NAAM[:1]}
    assert brp_gevonden(http, urls["api-proxy"], query) == []


@REG_40
@pytest.mark.scenario("""
    Given two persons in the BRP test set
    When both BSNs are looked up in one query through the api-proxy
    Then the BRP gives both persons
""")
def test_several_bsns_at_once(http: requests.Session, urls: dict[str, str]) -> None:
    """One query returns every known BSN it asks for (TA reg-40d)."""
    query = {
        "type": "RaadpleegMetBurgerservicenummer",
        "burgerservicenummer": [EREBOS, KIERKEGAARD],
        "fields": NAAM[:1],
    }
    assert {p["burgerservicenummer"] for p in brp_gevonden(http, urls["api-proxy"], query)} == {EREBOS, KIERKEGAARD}


@pytest.mark.parametrize(
    ("geslachtsnaam", "geboortedatum", "expected"),
    [("Kierkegaard", "1931-07-06", [KIERKEGAARD]), ("Janssen", "1900-01-01", [])],
)
@REG_40
@pytest.mark.scenario("""
    Given a geslachtsnaam and geboortedatum, of a person in the BRP test set or of no one
    When the BRP is searched by them through the api-proxy
    Then exactly the matching persons are found, or no one
""")
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
    assert [p["burgerservicenummer"] for p in brp_gevonden(http, urls["api-proxy"], query)] == expected


@REG_119
@pytest.mark.scenario("""
    Given a person in the BRP test set who lives at a known adres
    When the BRP is searched by that postcode and huisnummer through the api-proxy
    Then the person is among the residents found
    And a search on an unknown adres finds no one
""")
def test_search_by_postcode_and_huisnummer(http: requests.Session, urls: dict[str, str]) -> None:
    """Searching by postcode and huisnummer finds the residents of that address, and no one at an unknown one (TA reg-119)."""
    query = {"type": "ZoekMetPostcodeEnHuisnummer", "fields": NAAM[:1]}
    erebos = brp_gevonden(http, urls["api-proxy"], {**query, "postcode": "3224TT", "huisnummer": 4})
    assert EREBOS in [p["burgerservicenummer"] for p in erebos]
    assert brp_gevonden(http, urls["api-proxy"], {**query, "postcode": "1234AB", "huisnummer": 1}) == []


@pytest.mark.parametrize(
    ("query", "invalid"),
    [
        ({}, ("type", "required")),
        ({"type": "OnbekendType"}, ("type", "value")),
        ({**RAADPLEEG_EREBOS, "burgerservicenummer": ["abc"]}, ("burgerservicenummer[0]", "pattern")),
        (
            {**RAADPLEEG_EREBOS, "burgerservicenummer": list(repeat(EREBOS, MAX_BSNS + 1)), "fields": NAAM[:1]},
            ("burgerservicenummer", "maxItems"),
        ),
        (RAADPLEEG_EREBOS, ("fields", "required")),
        ({**RAADPLEEG_EREBOS, "fields": []}, ("fields", "minItems")),
        ({**RAADPLEEG_EREBOS, "fields": "burgerservicenummer,geslacht"}, ("fields", "array")),
        ({**RAADPLEEG_EREBOS, "fields": ["bestaatniet"]}, ("fields[0]", "fields")),
        ({**RAADPLEEG_EREBOS, "fields": ["gezag.type"]}, ("fields[0]", "fields")),
        (
            {"type": "ZoekMetGeslachtsnaamEnGeboortedatum", "geslachtsnaam": "Kierkegaard", "fields": NAAM[:1]},
            ("geboortedatum", "required"),
        ),
    ],
    ids=[
        "empty",
        "unknown-type",
        "invalid-bsn",
        "too-many-bsns",
        "no-fields",
        "empty-fields",
        "fields-as-string",
        "unknown-field",
        "gezag-subfield",
        "search-without-geboortedatum",
    ],
)
@REG_40
@REG_80
@REG_121
@BRP_FEATURES
@pytest.mark.scenario("""
    Given a BRP query with one fault in its type, its BSNs, its fields or its search parameters
    When it is sent to the BRP through the api-proxy
    Then the BRP refuses it with 400 and names the invalid parameter and the rule it breaks
""")
def test_invalid_query_is_refused(
    http: requests.Session, urls: dict[str, str], query: Mapping[str, object], invalid: tuple[str, str]
) -> None:
    """An invalid query answers 400 with the parameter and rule in invalidParams (TA reg-40c, reg-80, reg-121)."""
    body = expect_status(brp_personen(http, urls["api-proxy"], query), HTTPStatus.BAD_REQUEST).json()
    named = [(param["name"], param["code"]) for param in entries(body["invalidParams"])]
    assert invalid in named, f"invalidParams {named}, expected {invalid}"


@BRP_ADRESSERING
@pytest.mark.scenario("""
    Given a man in the BRP test set without a partner, living in Hellevoetsluis
    When his full name, age and adressering are asked through the api-proxy
    Then the BRP derives his full name, his age, the aanhef "Geachte heer" and his address lines
""")
def test_derived_name_age_and_adressering(http: requests.Session, urls: dict[str, str]) -> None:
    """The BRP derives volledigeNaam, leeftijd and adressering for a test-set person."""
    found = brp_persoon(http, urls["api-proxy"], EREBOS, ["naam.volledigeNaam", "leeftijd", "adressering"])
    adressering = {
        "aanhef": "Geachte heer Bultenaar",
        "aanschrijfwijze": {"naam": "E. Bultenaar"},
        "gebruikInLopendeTekst": "de heer Bultenaar",
        "adresregel1": "Plataanlaan 4",
        "adresregel2": "3224 TT  HELLEVOETSLUIS",
    }
    assert (found["naam"], found["adressering"]) == ({"volledigeNaam": "Erebos Bultenaar"}, adressering)
    assert isinstance(found["leeftijd"], int)


def aanschrijving(aanhef: str, naam: str, gebruik_in_lopende_tekst: str, aanspreekvorm: str = "") -> JsonObject:
    """Return the adressering fields aanhef, aanschrijfwijze and gebruikInLopendeTekst."""
    aanschrijfwijze = {"naam": naam, "aanspreekvorm": aanspreekvorm} if aanspreekvorm else {"naam": naam}
    return {"aanhef": aanhef, "aanschrijfwijze": aanschrijfwijze, "gebruikInLopendeTekst": gebruik_in_lopende_tekst}


@pytest.mark.parametrize(
    ("bsn", "expected"),
    [
        # Thea Kouwenhoven, naamgebruik P, partner Rozen Groeman.
        ("999993409", aanschrijving("Geachte mevrouw Groeman", "T. Groeman", "mevrouw Groeman")),
        # Kevin de Boer, naamgebruik P, partner Olivia Charbon.
        ("999996538", aanschrijving("Geachte heer Charbon", "K. Charbon", "de heer Charbon")),
        # Wilma van Zon, naamgebruik V, partner Gerrit den Braber.
        (
            "999993112",
            aanschrijving("Geachte mevrouw Den Braber-van Zon", "W. den Braber-van Zon", "mevrouw Den Braber-van Zon"),
        ),
        # A jonkvrouw 'S Streeveld with a partner (gravin te Schaars), naamgebruik N: no predicaat.
        (
            "999994669",
            aanschrijving(
                "Geachte mevrouw 'S Streeveld-te Schaars",
                "Ż.Å.Đ. 'S Streeveld-te Schaars",
                "mevrouw 'S Streeveld-te Schaars",
            ),
        ),
        # Róza Żywiałowska, naamgebruik E, partner graaf Wałęsa: no hoffelijkheidstitel.
        ("999990172", aanschrijving("Geachte mevrouw Żywiałowska", "R.M. Żywiałowska", "mevrouw Żywiałowska")),
        # Guðrún Sigurðardóttir, naamgebruik P, partner graaf De Marchant et d'Ansembourg: hoffelijkheidstitel.
        (
            "999991553",
            aanschrijving(
                "Hooggeboren vrouwe",
                "G.S. gravin De Marchant et d'Ansembourg",
                "gravin De Marchant et d'Ansembourg",
                "De hooggeboren vrouwe",
            ),
        ),
        # Carolina barones van der Hom, naamgebruik P, partner baron van Brest naar Kempen.
        (
            "999994037",
            aanschrijving(
                "Hoogwelgeboren vrouwe",
                "C. barones van Brest naar Kempen",
                "barones van Brest naar Kempen",
                "De hoogwelgeboren vrouwe",
            ),
        ),
        # Robert Johannes graaf van der Leijenhorst, no partner.
        (
            "999992922",
            aanschrijving(
                "Hooggeboren heer",
                "R.J. graaf van der Leijenhorst",
                "graaf van der Leijenhorst",
                "De hooggeboren heer",
            ),
        ),
        # Catherine barones Van Nassau la Lecq, no partner.
        (
            "999992016",
            aanschrijving(
                "Hoogwelgeboren vrouwe",
                "C. barones Van Nassau la Lecq",
                "barones Van Nassau la Lecq",
                "De hoogwelgeboren vrouwe",
            ),
        ),
        # Hendrik Jan Coenraad Maurits ridder den Brinck, no partner.
        (
            "999990160",
            aanschrijving(
                "Hoogwelgeboren heer", "H.J.C.M. ridder den Brinck", "ridder den Brinck", "De hoogwelgeboren heer"
            ),
        ),
    ],
    ids=[
        "partner-naam",
        "partner-naam-man",
        "partner-naam-voor-eigen-naam",
        "predicaat-vrouw-met-partner",
        "eigen-naam-adellijke-partner",
        "hoffelijkheidstitel",
        "titel-en-hoffelijkheidstitel",
        "graaf",
        "barones",
        "ridder",
    ],
)
@BRP_ADRESSERING
@pytest.mark.scenario("""
    Given a person in the BRP test set with a partner, an adellijke titel or predicaat, or both
    When the aanhef, aanschrijfwijze and gebruikInLopendeTekst are asked through the api-proxy
    Then the BRP composes them by the person's aanduiding naamgebruik from the own and the partner's name
    And uses the own titel, or the hoffelijkheidstitel of a woman who uses the name of a partner with a titel
""")
def test_adressering_with_partner_or_adellijke_titel(
    http: requests.Session, urls: dict[str, str], bsn: str, expected: JsonObject
) -> None:
    """The BRP derives aanhef, aanschrijfwijze and gebruikInLopendeTekst by the rules for partners and titels."""
    found = brp_persoon(http, urls["api-proxy"], bsn, [f"adressering.{field}" for field in expected])
    assert found["adressering"] == expected


@REG_150
@pytest.mark.scenario("""
    Given a BSN that fails the eleven-test
    When it is looked up through the api-proxy
    Then the BRP refuses it with 400 or 422, or finds no one
""")
def test_bsn_failing_the_eleven_test_finds_no_one(http: requests.Session, urls: dict[str, str]) -> None:
    """A BSN that fails the eleven-test is refused, or finds no one; never 5xx (TA reg-150)."""
    query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": ["123456789"]}
    response = brp_personen(http, urls["api-proxy"], {**query, "fields": ["burgerservicenummer"]})
    expect_status(response, HTTPStatus.OK, HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY)
    if response.status_code == HTTPStatus.OK:
        assert response.json()["personen"] == []


@REG_11
@pytest.mark.scenario("""
    Given a person in the BRP test set
    When the person is looked up on the Haal Centraal V1 path through the api-proxy
    Then the BRP answers 405, as it serves V2 only
""")
def test_v1_lookup_is_not_offered(http: requests.Session, urls: dict[str, str]) -> None:
    """The BRP serves Haal Centraal V2 only: the V1 path answers 405 (TA reg-11, finding 14)."""
    v1 = urls["api-proxy"] + BRP_PERSONEN.replace("personen", f"ingeschrevenpersonen/{EREBOS}")
    expect_status(http.get(v1), HTTPStatus.METHOD_NOT_ALLOWED)
