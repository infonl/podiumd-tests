"""Open Zaak zaken: CRUD, unique identificatie, relations, zaakobjecten, geometry and listing.

Ported from TA interaction 02 and regression 28, 36, 38, 43, 52, 55 and 59.
"""

from __future__ import annotations

import secrets

from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


@pytest.mark.core
def test_zaak_lifecycle(openzaak: ApiClient, registry: ResourceRegistry, test_zaaktype: JsonObject) -> None:
    """A zaak reads back with an identificatie, accepts a PATCH and is gone after DELETE."""
    zaak = make_zaak(openzaak, registry, str(test_zaaktype["url"]))
    url = str(zaak["url"])
    read = openzaak.get(url)
    assert (read["zaaktype"], read["omschrijving"]) == (test_zaaktype["url"], registry.tagged("zaak"))
    assert read["identificatie"]
    assert openzaak.patch(url, {"toelichting": "podiumd-tests"})["toelichting"] == "podiumd-tests"
    openzaak.delete(url)
    openzaak.request("GET", url, 404)


def test_identificatie_is_unique_under_concurrent_creates(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """Five parallel creates with one identificatie leave exactly one zaak (TA reg-38a)."""
    identificatie = registry.tagged(f"uniek-{secrets.token_hex(3)}")

    def create(_: int) -> int:
        body = {
            "bronorganisatie": TEST_CATALOGUS_RSIN,
            "verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN,
            "zaaktype": parts.zaaktype,
            "startdatum": today(),
            "omschrijving": registry.tagged("zaak"),
            "identificatie": identificatie,
        }
        response = openzaak.http.post(openzaak.url(f"{ZAKEN}/zaken"), json=body, headers=openzaak.headers())
        if response.status_code == HTTPStatus.CREATED:
            url = str(response.json()["url"])
            registry.add(f"zaak {url}", lambda: delete_zaak(openzaak, url))
        return response.status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(create, range(5)))
    assert statuses.count(HTTPStatus.CREATED) == 1, statuses
    assert len(openzaak.list(f"{ZAKEN}/zaken", {"identificatie": identificatie})) == 1


def relations(zaak: JsonObject) -> list[tuple[object, object]]:
    """(url, aardRelatie) of a zaak's relevanteAndereZaken."""
    return [(r["url"], r["aardRelatie"]) for r in entries(zaak["relevanteAndereZaken"])]


def test_relevante_andere_zaken(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A zaak refers to two vervolgzaken, one of which refers to a third (TA reg-28, 59)."""
    hoofd, a, b, b1 = (make_zaak(openzaak, registry, parts.zaaktype) for _ in range(4))
    openzaak.patch(str(b["url"]), {"relevanteAndereZaken": [{"url": b1["url"], "aardRelatie": "vervolg"}]})
    relaties = [{"url": z["url"], "aardRelatie": "vervolg"} for z in (a, b)]
    openzaak.patch(str(hoofd["url"]), {"relevanteAndereZaken": relaties})
    assert relations(openzaak.get(str(hoofd["url"]))) == [(a["url"], "vervolg"), (b["url"], "vervolg")]
    assert relations(openzaak.get(str(b["url"]))) == [(b1["url"], "vervolg")]
    for zaak in (hoofd, b):  # a zaak referred to cannot be deleted
        openzaak.patch(str(zaak["url"]), {"relevanteAndereZaken": []})


def test_zaakobject_adres(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """An address zaakobject is found through the zaak (TA reg-36)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    adres = {
        "identificatie": "0518200000123456",
        "wplWoonplaatsNaam": "Den Haag",
        "gorOpenbareRuimteNaam": "Spuiplein",
        "huisnummer": 70,
        "huisletter": "",
        "huisnummertoevoeging": "",
        "postcode": "2511DN",
    }
    body = {
        "zaak": zaak["url"],
        "objectType": "adres",
        "relatieomschrijving": registry.tagged("adres"),
        "objectIdentificatie": adres,
    }
    zaakobject = openzaak.post(f"{ZAKEN}/zaakobjecten", body)
    registry.add("zaakobject", lambda: openzaak.delete(str(zaakobject["url"])))
    found = openzaak.list(f"{ZAKEN}/zaakobjecten", {"zaak": str(zaak["url"])})
    assert [section(z, "objectIdentificatie").get("postcode") for z in found] == ["2511DN"]


def test_zaakgeometrie_and_zoek_within(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A zaak with a point is found by _zoek within a polygon around it, after moving it there (TA reg-52)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype, zaakgeometrie={"type": "Point", "coordinates": [4.31, 52.075]})
    assert section(zaak, "zaakgeometrie").get("coordinates") == [4.31, 52.075]
    openzaak.patch(str(zaak["url"]), {"zaakgeometrie": {"type": "Point", "coordinates": [5.121, 52.094]}})
    vlak = {"type": "Polygon", "coordinates": [[[5.0, 52.0], [5.3, 52.0], [5.3, 52.2], [5.0, 52.2], [5.0, 52.0]]]}
    zoek = openzaak.request(
        "POST", f"{ZAKEN}/zaken/_zoek", 200, json={"zaakgeometrie": {"within": vlak}, "zaaktype": parts.zaaktype}
    ).json()
    assert str(zaak["url"]) in {str(z["url"]) for z in entries(zoek["results"])}


def test_zaken_by_zaaktype_across_pages(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """All new zaken of the zaaktype are listed, following every page (TA reg-43, 55)."""
    created = {str(make_zaak(openzaak, registry, parts.zaaktype)["url"]) for _ in range(3)}
    listed = openzaak.list(f"{ZAKEN}/zaken", {"zaaktype": parts.zaaktype})
    assert created <= {str(z["url"]) for z in listed}
    assert all(z["zaaktype"] == parts.zaaktype for z in listed)
