"""BRP (Haal Centraal personen) and KvK through the environment's api-proxy, as the apps call them."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import NamedTuple

from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Mapping

    import requests

    from podiumd_tests.json_data import JsonObject

BRP_PERSONEN = "/haalcentraal/api/brp/personen"
BAG_ADRESSEN = "/lvbag/individuelebevragingen/v2/adressen"
# The nummeraanduiding of Dam 1, Amsterdam: in the BAG and in podiumd-minikube's BAG mock.
BAG_DAM = "0363200003761447"
KVK_ZOEKEN = "/api/v2/zoeken"
KVK_BASISPROFIELEN = "/api/v1/basisprofielen"
KVK_VESTIGINGSPROFIELEN = "/api/v1/vestigingsprofielen"
# Erebos Bultenaar, a person of the BRP test set; also the DigiD test inwoner's BSN.
EREBOS = "999990019"
# Kierkegaard, born 1931-07-06, another person of the BRP test set; only the ontvangstbevestiging test of an
# initiator gives it an Open Klant partij.
KIERKEGAARD = "999990020"
# Merel Kooyman, a person of the BRP test set; only the Open Formulieren klantprofiel test gives it an Open Klant
# partij.
KOOYMAN = "999993847"
# Lukas Klamer, a person of the BRP test set that only the ZAC e-mail test gives an Open Klant partij.
KLAMER = "999991723"
# Persons of the BRP test set with one edge case each.
BRP_OVERLEDEN = "999999655"
BRP_EMIGRATIE = "999991024"
BRP_GEHEIMHOUDING = "999990792"
# The api-proxy of every estate the suite tests routes KvK to KvK's test API; its test set has
# Test BV Donald, with this hoofdvestiging address.
KVK_TEST_NUMMER = "68750110"
KVK_TEST_RSIN = "857587973"
KVK_TEST_HOOFDVESTIGING = "000037178598"
# The nevenvestiging of KVK_TEST_NUMMER in the KvK test set.
KVK_TEST_VESTIGING = "000037178601"
# A vestiging of another company in the KvK test set (Test VOF Guus de 2e).
KVK_ANDERE_VESTIGING = "000038509490"
KVK_TEST_ADRES = {"postcode": "8823SJ", "huisnummer": "3"}


class KvkBedrijf(NamedTuple):
    """A company of KvK's test set: its KvK-nummer, the naam of its basisprofiel and the rechtsvorm of its eigenaar."""

    kvk_nummer: str
    naam: str
    rechtsvorm: str


# One company of KvK's test set per rechtsvorm. The coöperatie of the set (55344526) has no basisprofiel (IPD0005).
KVK_RECHTSVORMEN = {
    "eenmanszaak": KvkBedrijf("69599084", "Test EMZ Dagobert", "Eenmanszaak"),
    "bv": KvkBedrijf(KVK_TEST_NUMMER, "Test BV Donald", "Besloten vennootschap"),
    "nv": KvkBedrijf("68727720", "Test NV Katrien", "Naamloze Vennootschap"),
    "stichting": KvkBedrijf("69599068", "Test Stichting Bolderbast", "Stichting"),
    "vof": KvkBedrijf("90005414", "Regional Qvolane - MA", "Vennootschap Onder Firma"),
    "maatschap": KvkBedrijf("90001745", "Free Movelax", "Maatschap"),
    "cv": KvkBedrijf("90003942", "Global Bigdofind", "Commanditaire Vennootschap"),
    "vve": KvkBedrijf("90000749", "Global Conron", "Vereniging van Eigenaars"),
    "kerkgenootschap": KvkBedrijf("90002520", "Global Kontex - MA", "Kerkgenootschap"),
    "owm": KvkBedrijf("90002490", "Onderlinge Waarborgmaatschappij Local Dongplus", "Onderlinge Waarborg Maatschappij"),
    "kerspel": KvkBedrijf("55505201", "Free Stathex", "Kerspel"),
}
# The KvK-nummers of KvK's test set that answer an error: 404 with IPD0005 (basisprofiel) or IPD5200 (zoeken).
KVK_FOUTMELDINGEN = ("90004973", "90002903")
KVK_GEEN_PRODUCT = "IPD0005"
KVK_GEEN_RESULTATEN = "IPD5200"


def brp_personen(http: requests.Session, proxy_url: str, query: Mapping[str, object]) -> requests.Response:
    """POST a Haal Centraal personen query (type, burgerservicenummer or search fields, fields)."""
    return http.post(proxy_url + BRP_PERSONEN, json=query)


def brp_gevonden(http: requests.Session, proxy_url: str, query: Mapping[str, object]) -> list[JsonObject]:
    """Return the personen a Haal Centraal query finds; the BRP must answer 200 with the query's type."""
    body = expect_status(brp_personen(http, proxy_url, query), HTTPStatus.OK).json()
    if body["type"] != query["type"]:
        msg = f"BRP answered type {body['type']} to a {query['type']} query"
        raise AssertionError(msg)
    return entries(body["personen"])


def brp_persoon(http: requests.Session, proxy_url: str, bsn: str, fields: list[str]) -> JsonObject:
    """Return the fields of the one person the BRP has under a BSN."""
    query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [bsn], "fields": fields}
    found = brp_gevonden(http, proxy_url, query)
    if len(found) != 1:
        msg = f"BRP found {len(found)} personen under BSN {bsn}, expected 1"
        raise AssertionError(msg)
    return found[0]


def bag_adres(http: requests.Session, proxy_url: str, nummeraanduiding: str) -> requests.Response:
    """GET the BAG adres of a nummeraanduiding."""
    return http.get(f"{proxy_url}{BAG_ADRESSEN}/{nummeraanduiding}", headers={"Accept": "*/*"})


def kvk_zoeken(http: requests.Session, proxy_url: str, query: Mapping[str, str]) -> requests.Response:
    """GET a KvK zoeken query."""
    return http.get(proxy_url + KVK_ZOEKEN, params=query)


def kvk_basisprofiel(http: requests.Session, proxy_url: str, kvk_nummer: str) -> requests.Response:
    """GET the basisprofiel of a KvK number."""
    return http.get(f"{proxy_url}{KVK_BASISPROFIELEN}/{kvk_nummer}", params={"geoData": "false"})


def kvk_vestigingsprofiel(http: requests.Session, proxy_url: str, vestigingsnummer: str) -> requests.Response:
    """GET the vestigingsprofiel of a vestigingsnummer."""
    return http.get(f"{proxy_url}{KVK_VESTIGINGSPROFIELEN}/{vestigingsnummer}", params={"geoData": "false"})


def kvk_foutcodes(response: requests.Response) -> set[str]:
    """Return the codes of a KvK error answer's fout list."""
    return {str(fout.get("code")) for fout in entries(response.json().get("fout"))}
