"""BRP inOnderzoek through the api-proxy: which asked fields the BRP marks as in onderzoek, and since when.

The BSNs are from the BRP test set that the personen mock serves, each with one aanduiding in onderzoek.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import brp_persoon
from podiumd_tests.json_data import section

if TYPE_CHECKING:
    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("api-proxy"),
    pytest.mark.source(
        "external BRP-API/Haal-Centraal-BRP-bevragen features/bevragen/**/in-onderzoek.feature",
        "The BRP API marks each asked field, also a derived one, whose source data is in onderzoek.",
    ),
]

PERSOON = ("burgerservicenummer", "geslacht", "leeftijd")
AANSCHRIJVING = ("aanhef", "aanschrijfwijze", "gebruikInLopendeTekst")
ADRESREGELS = ("adresregel1", "adresregel2", "adresregel3", "land")
GEMEENTE = ("gemeenteVanInschrijving", "datumInschrijvingInGemeente")
NAAM = ("voornamen", "adellijkeTitelPredicaat", "voorvoegsel", "geslachtsnaam", "voorletters", "volledigeNaam")
# Jan-Kees Brouwers: hele categorie persoon (010000) in onderzoek.
BROUWERS = "999993355"
# Debrabandere: geslachtsaanduiding (010410) in onderzoek.
DEBRABANDERE = "999991310"
# Carsten Antonius du Burck: hele categorie verblijfplaats (080000) in onderzoek.
DU_BURCK = "999993136"


def in_onderzoek(ingang: str, datum: str, lang_formaat: str, *fields: str) -> JsonObject:
    """Return an inOnderzoek with each field true and the date the onderzoek started under ingang."""
    return {**dict.fromkeys(fields, True), ingang: {"type": "Datum", "datum": datum, "langFormaat": lang_formaat}}


def adressering(*fields: str) -> list[str]:
    """Return the fields values that ask these adressering fields."""
    return [f"adressering.{field}" for field in fields]


@pytest.mark.parametrize(
    ("bsn", "fields", "group", "expected"),
    [
        (
            BROUWERS,
            list(PERSOON),
            "",
            in_onderzoek("datumIngangOnderzoekPersoon", "2021-12-28", "28 december 2021", *PERSOON),
        ),
        # Erebos Bultenaar: geboortedatum (010310) in onderzoek.
        (
            EREBOS,
            list(PERSOON),
            "",
            in_onderzoek("datumIngangOnderzoekPersoon", "2010-01-01", "1 januari 2010", "leeftijd"),
        ),
        (EREBOS, ["burgerservicenummer"], "", {}),
        (
            DEBRABANDERE,
            list(PERSOON),
            "",
            in_onderzoek("datumIngangOnderzoekPersoon", "2010-08-22", "22 augustus 2010", "geslacht"),
        ),
        (
            DEBRABANDERE,
            ["naam"],
            "naam",
            in_onderzoek("datumIngangOnderzoek", "2010-08-22", "22 augustus 2010", "volledigeNaam"),
        ),
        # Amandine le Sommer: hele groep naam (010200) in onderzoek.
        ("999992466", ["naam"], "naam", in_onderzoek("datumIngangOnderzoek", "1994-03-10", "10 maart 1994", *NAAM)),
        (
            BROUWERS,
            adressering(*AANSCHRIJVING),
            "adressering",
            in_onderzoek("datumIngangOnderzoekPersoon", "2021-12-28", "28 december 2021", *AANSCHRIJVING),
        ),
        (
            DU_BURCK,
            adressering(*ADRESREGELS),
            "adressering",
            in_onderzoek("datumIngangOnderzoekVerblijfplaats", "1999-11-07", "7 november 1999", *ADRESREGELS),
        ),
        (
            DU_BURCK,
            list(GEMEENTE),
            "",
            in_onderzoek("datumIngangOnderzoekGemeente", "1999-11-07", "7 november 1999", *GEMEENTE),
        ),
    ],
    ids=[
        "persoon",
        "geboortedatum",
        "geboortedatum-niet-gevraagd",
        "geslacht",
        "geslacht-volledige-naam",
        "naam",
        "persoon-adressering",
        "verblijfplaats-adresregels",
        "verblijfplaats-gemeente",
    ],
)
@pytest.mark.scenario("""
    Given a person in the BRP test set with a category, group or field of the persoonslijst in onderzoek
    When fields that are, or are derived from, that data are asked through the api-proxy
    Then the BRP marks exactly those fields as in onderzoek, with the date the onderzoek started
    And marks nothing when the asked fields do not depend on that data
""")
def test_in_onderzoek_of_asked_fields(
    http: requests.Session, urls: dict[str, str], bsn: str, fields: list[str], group: str, expected: JsonObject
) -> None:
    """The BRP gives inOnderzoek for exactly the asked fields whose source data is in onderzoek."""
    found = brp_persoon(http, urls["api-proxy"], bsn, fields)
    scope = section(found, group) if group else found
    assert section(scope, "inOnderzoek") == expected
