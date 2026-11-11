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


@pytest.mark.source(
    "TA interaction/02-zaak-creatie.spec.ts",
    "Create a zaak through the ZGW Zaken API as Open Formulieren does and find it back by its identificatie.",
)
@pytest.mark.core
@pytest.mark.scenario("""
    When a zaak of the test zaaktype is made in Open Zaak
    Then it reads back with its zaaktype, omschrijving and an identificatie
    When its toelichting is changed
    Then the zaak has the new toelichting
    When the zaak is deleted
    Then it is no longer found
""")
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


@pytest.mark.source(
    "TA regression/38-concurrency-uniqueness.spec.ts",
    "Under concurrent creates with one bronorganisatie and identificatie, Open Zaak keeps exactly one zaak.",
)
@pytest.mark.scenario("""
    When five zaken with the same identificatie are created in Open Zaak at the same time
    Then exactly one create succeeds
    And a search by the identificatie finds one zaak
""")
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


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule zrc-002",
    "The identificatie of a zaak is unique per bronorganisatie, also when a zaak is changed.",
)
@pytest.mark.scenario("""
    Given two zaken in Open Zaak
    When the second zaak is given the identificatie of the first
    Then Open Zaak refuses the change
    And the error names the identificatie
""")
@pytest.mark.parametrize("method", ["PUT", "PATCH"])
def test_identificatie_cannot_be_changed_to_one_in_use(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, method: str
) -> None:
    """PUT or PATCH of a zaak to another zaak's identificatie answers 400 and names identificatie."""
    eerste = make_zaak(openzaak, registry, parts.zaaktype)
    tweede = make_zaak(openzaak, registry, parts.zaaktype)
    fields = {"identificatie": eerste["identificatie"]}
    body = {**openzaak.get(str(tweede["url"])), **fields} if method == "PUT" else fields
    response = openzaak.request(method, str(tweede["url"]), HTTPStatus.BAD_REQUEST, json=body)
    assert "identificatie" in {str(p["name"]) for p in entries(response.json()["invalidParams"])}


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule zrc-009",
    "A zaak without vertrouwelijkheidaanduiding gets its zaaktype's; an explicit one is kept.",
)
@pytest.mark.scenario("""
    Given the test zaaktype
    When a zaak is created without a vertrouwelijkheidaanduiding
    Then the zaak has the vertrouwelijkheidaanduiding of its zaaktype
    And a zaak created with one keeps it
""")
def test_vertrouwelijkheidaanduiding_defaults_to_the_zaaktypes(
    openzaak: ApiClient, registry: ResourceRegistry, test_zaaktype: JsonObject
) -> None:
    """A zaak without vertrouwelijkheidaanduiding takes the zaaktype's; an explicit value is kept."""
    zaaktype = str(test_zaaktype["url"])
    derived = make_zaak(openzaak, registry, zaaktype, vertrouwelijkheidaanduiding=None)
    explicit = make_zaak(openzaak, registry, zaaktype, vertrouwelijkheidaanduiding="geheim")
    assert derived["vertrouwelijkheidaanduiding"] == test_zaaktype["vertrouwelijkheidaanduiding"]
    assert explicit["vertrouwelijkheidaanduiding"] == "geheim"


def relations(zaak: JsonObject) -> list[tuple[object, object]]:
    """(url, aardRelatie) of a zaak's relevanteAndereZaken."""
    return [(r["url"], r["aardRelatie"]) for r in entries(zaak["relevanteAndereZaken"])]


@pytest.mark.source(
    "TA regression/28-gerelateerde-zaken.spec.ts", "A hoofdzaak refers to its deelzaken through relevanteAndereZaken."
)
@pytest.mark.source(
    "TA regression/59-zaak-relatie-keten.spec.ts",
    "Zaak relations chain three levels deep: hoofdzaak, deelzaken and a sub-deelzaak.",
)
@pytest.mark.scenario("""
    Given four zaken in Open Zaak
    When a hoofdzaak refers to two of them as vervolg, and one of those refers to the fourth
    Then the hoofdzaak lists both vervolgzaken
    And that vervolgzaak lists the fourth zaak
""")
def test_relevante_andere_zaken(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A zaak refers to two vervolgzaken, one of which refers to a third (TA reg-28, 59)."""
    hoofd = make_zaak(openzaak, registry, parts.zaaktype)
    a, b, b1 = (make_zaak(openzaak, registry, parts.zaaktype) for _ in range(3))
    openzaak.patch(str(b["url"]), {"relevanteAndereZaken": [{"url": b1["url"], "aardRelatie": "vervolg"}]})
    relaties = [{"url": z["url"], "aardRelatie": "vervolg"} for z in (a, b)]
    openzaak.patch(str(hoofd["url"]), {"relevanteAndereZaken": relaties})
    assert relations(openzaak.get(str(hoofd["url"]))) == [(a["url"], "vervolg"), (b["url"], "vervolg")]
    assert relations(openzaak.get(str(b["url"]))) == [(b1["url"], "vervolg")]
    for zaak in (hoofd, b):  # a zaak referred to cannot be deleted
        openzaak.patch(str(zaak["url"]), {"relevanteAndereZaken": []})


@pytest.mark.source(
    "TA regression/36-zaakobject-koppeling.spec.ts",
    "A zaak refers to an external registration, such as a BAG address, through a zaakobject.",
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When an address is linked to the zaak as zaakobject
    Then the zaak's zaakobjecten hold only that address, with its postcode
""")
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


@pytest.mark.source(
    "TA regression/52-zaak-geometrie.spec.ts",
    "Location-bound zaken carry a GeoJSON zaakgeometrie that can be read and updated.",
)
@pytest.mark.scenario("""
    When a zaak with a point as zaakgeometrie is made in Open Zaak
    Then the zaak holds that point
    When the point is moved to another place
    Then a search for zaken within an area around the new place finds the zaak
""")
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


@pytest.mark.source(
    "TA regression/43-pagineren-filtering.spec.ts",
    "ZAC, the portal and KISS must page and filter the zaken list of a municipality with thousands of zaken.",
)
@pytest.mark.source(
    "TA regression/55-multi-zaaktype.spec.ts", "Zaken lists filter on one zaaktype, as ZAC work lists and KISS do."
)
@pytest.mark.scenario("""
    Given three new zaken of the test zaaktype in Open Zaak
    When the zaken of that zaaktype are listed across all pages
    Then the list contains the three zaken
    And every listed zaak has that zaaktype
""")
def test_zaken_by_zaaktype_across_pages(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """All new zaken of the zaaktype are listed, following every page (TA reg-43, 55)."""
    created = {str(make_zaak(openzaak, registry, parts.zaaktype)["url"]) for _ in range(3)}
    listed = openzaak.list(f"{ZAKEN}/zaken", {"zaaktype": parts.zaaktype})
    assert created <= {str(z["url"]) for z in listed}
    assert all(z["zaaktype"] == parts.zaaktype for z in listed)


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW features, ZRC 1.7 reserveer_zaaknummer",
    "A reserved zaaknummer goes to the next zaak that asks for it, and only to that one.",
)
@pytest.mark.scenario("""
    Given two zaaknummers reserved in Open Zaak
    When a zaak is created with the first one
    Then it gets that identificatie
    And a second zaak with the same identificatie is refused
""")
def test_reserved_zaaknummer_goes_to_one_zaak(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """POST zaaknummer_reserveren returns identificaties; a zaak takes one, a second zaak with it is a 400."""
    reserved = openzaak.request(
        "POST",
        f"{ZAKEN}/zaaknummer_reserveren",
        HTTPStatus.CREATED,
        HTTPStatus.OK,
        json={"bronorganisatie": TEST_CATALOGUS_RSIN, "aantal": 2},
    ).json()
    identificaties = [str(r["zaaknummer"]) for r in entries(reserved)]
    assert len(set(identificaties)) == 2, reserved
    zaak = make_zaak(openzaak, registry, parts.zaaktype, identificatie=identificaties[0])
    assert zaak["identificatie"] == identificaties[0]
    body = {
        "bronorganisatie": TEST_CATALOGUS_RSIN,
        "verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN,
        "zaaktype": parts.zaaktype,
        "startdatum": today(),
        "identificatie": identificaties[0],
    }
    response = openzaak.request("POST", f"{ZAKEN}/zaken", HTTPStatus.BAD_REQUEST, json=body)
    assert "identificatie" in {str(p["name"]) for p in entries(response.json()["invalidParams"])}
