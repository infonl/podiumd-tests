"""KISS's person and company search, through its own BRP and KvK proxies, found and not found.

Ported from KISS's Playwright suite (Kiss.Bff.EndToEndTest/ContactMomentSearch), as the BFF calls of its search
page. The api-proxy itself is tested in tests/component/basisregistraties.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import BRP_EMIGRATIE
from podiumd_tests.basisregistraties import BRP_GEHEIMHOUDING
from podiumd_tests.basisregistraties import BRP_OVERLEDEN
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KIERKEGAARD
from podiumd_tests.basisregistraties import KVK_FOUTMELDINGEN
from podiumd_tests.basisregistraties import KVK_GEEN_RESULTATEN
from podiumd_tests.basisregistraties import KVK_RECHTSVORMEN
from podiumd_tests.basisregistraties import KVK_TEST_ADRES
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.basisregistraties import kvk_foutcodes
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kcc import kiss_brp_personen
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.basisregistraties import KvkBedrijf
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
    """KISS's BRP search finds the number of test-set persons, the expected one among them."""
    found = kiss_brp_personen(kiss_session(KCC), urls["kiss"], {**query, "fields": ["burgerservicenummer"]})
    bsns = [str(p.get("burgerservicenummer")) for p in found]
    assert len(bsns) == count, bsns
    assert expected is None or expected in bsns


# The fields KISS's frontend asks for a person by BSN (src/services/brp/service.ts).
KISS_PERSOON_FIELDS = [
    "burgerservicenummer",
    "geboorte.datum",
    "geslacht",
    "adressering.adresregel1",
    "adressering.adresregel2",
    "adressering.adresregel3",
    "adressering.land.omschrijving",
    "naam.voornamen",
    "naam.voorvoegsel",
    "naam.geslachtsnaam",
    "geboorte.land",
    "geboorte.plaats",
]


@pytest.mark.parametrize(
    ("bsn", "geheim", "land"),
    [
        pytest.param(EREBOS, False, None, id="ingezetene"),
        pytest.param(BRP_GEHEIMHOUDING, True, None, id="geheimhouding"),
        pytest.param(BRP_OVERLEDEN, False, None, id="overleden"),
        pytest.param(BRP_EMIGRATIE, False, "Verenigde Arabische Emiraten", id="emigratie"),
    ],
)
@pytest.mark.source(
    "upstream klantinteractie-servicesysteem/KISS-frontend src/features/persoon/persoon-details/BrpGegevens.vue",
    "KISS warns that a person has geheimhouding of persoonsgegevens, and shows the BRP's adresregels.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    And a person of the BRP test set: an inwoner, or one with geheimhouding, overleden or emigrated
    When the medewerker opens the person found by BSN
    Then KISS gets the person's naam and first adresregel
    And gets the geheimhouding indication, for its warning, only for the person with geheimhouding
    And gets the land only for the address abroad
""")
def test_person_details_carry_geheimhouding_and_address(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    bsn: str,
    geheim: bool,  # noqa: FBT001  # a parameter of the test
    land: str | None,
) -> None:
    """KISS's BSN query, with its own fields, gives naam, adresregel1, land and geheimhoudingPersoonsgegevens.

    KISS does not ask for geheimhoudingPersoonsgegevens; the BRP adds it when it is true.
    """
    query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [bsn], "fields": KISS_PERSOON_FIELDS}
    personen = kiss_brp_personen(kiss_session(KCC), urls["kiss"], query)
    assert [p.get("burgerservicenummer") for p in personen] == [bsn]
    persoon = personen[0]
    adressering = section(persoon, "adressering")
    assert section(persoon, "naam").get("geslachtsnaam")
    assert adressering.get("adresregel1")
    assert bool(persoon.get("geheimhoudingPersoonsgegevens")) is geheim
    assert section(adressering, "land").get("omschrijving") == land


# A KvK test-set address with several vestigingen of another company (90004051).
KVK_SEVERAL_ADRES = {"postcode": "2352SZ", "huisnummer": "37"}


@pytest.mark.parametrize(
    ("query", "kvk_nummer", "minimum"),
    [
        pytest.param({"kvkNummer": KVK_TEST_NUMMER}, KVK_TEST_NUMMER, 2, id="kvknummer-several"),
        pytest.param({"kvkNummer": "12345678"}, None, 0, id="kvknummer-unknown"),
        *(pytest.param({"kvkNummer": n}, None, 0, id=f"kvknummer-foutmelding-{n}") for n in KVK_FOUTMELDINGEN),
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
    And finds nothing for an unknown KvK number, naam or address, or a KvK number that KvK answers with an error
""")
def test_company_search(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    query: dict[str, str],
    kvk_nummer: str | None,
    minimum: int,
) -> None:
    """KISS's KvK search gives at least the minimum of results of the KvK number, or nothing.

    Nothing is no results, or 404 with fout code IPD5200, which KISS shows as no results; any other 404 is an error.
    """
    response = kiss_session(KCC).get(f"{urls['kiss']}/api/kvk/v2/zoeken", params=query)
    if kvk_nummer is None and response.status_code == HTTPStatus.NOT_FOUND:
        assert kvk_foutcodes(response) == {KVK_GEEN_RESULTATEN}
        return
    numbers = [
        str(r.get("kvkNummer")) for r in entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))
    ]
    if kvk_nummer is None:
        assert numbers == []
    else:
        assert numbers.count(kvk_nummer) >= minimum, numbers


@pytest.mark.parametrize("bedrijf", KVK_RECHTSVORMEN.values(), ids=list(KVK_RECHTSVORMEN))
@pytest.mark.source(
    "upstream klantinteractie-servicesysteem/KISS-frontend src/services/kvk/service.ts",
    "KISS's company search reads the vestigingsprofiel of each vestiging found, and the eigenaar of the company.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to KISS
    And a company of KvK's test set of each rechtsvorm
    When the medewerker searches KvK by its KvK number
    Then KISS lists the company with a naam
    And gets the vestigingsprofiel of each vestiging listed
    And gets the company's eigenaar with its rechtsvorm
""")
def test_company_of_each_rechtsvorm(
    kiss_session: Callable[[KeycloakUser], requests.Session], urls: dict[str, str], bedrijf: KvkBedrijf
) -> None:
    """KISS's zoeken, vestigingsprofielen and eigenaar calls answer for a KvK test company of each rechtsvorm."""
    kiss, kvk = kiss_session(KCC), f"{urls['kiss']}/api/kvk"
    response = kiss.get(f"{kvk}/v2/zoeken", params={"kvkNummer": bedrijf.kvk_nummer})
    found = entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))
    assert found
    assert all(r.get("kvkNummer") == bedrijf.kvk_nummer and r.get("naam") for r in found), found
    vestigingen = sorted({str(r["vestigingsnummer"]) for r in found if r.get("vestigingsnummer")})
    for vestiging in vestigingen:
        profiel = expect_status(kiss.get(f"{kvk}/v1/vestigingsprofielen/{vestiging}"), HTTPStatus.OK).json()
        assert profiel["kvkNummer"] == bedrijf.kvk_nummer
    eigenaar = expect_status(kiss.get(f"{kvk}/v1/basisprofielen/{bedrijf.kvk_nummer}/eigenaar"), HTTPStatus.OK)
    assert eigenaar.json().get("rechtsvorm") == bedrijf.rechtsvorm
