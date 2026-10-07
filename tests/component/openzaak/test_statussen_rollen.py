"""Open Zaak statussen, rollen and closing a zaak.

Ported from TA interaction 10 and regression 15, 16, 39, 41, 50, 56 and 122; closing with
a resultaat and the eindstatus is new (TA's seed had no resultaattype).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openklant import random_kvk_nummer
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]

BSN_FILTER = "rol__betrokkeneIdentificatie__natuurlijkPersoon__inpBsn"


def urls(objects: list[JsonObject]) -> set[str]:
    """The urls of a list of objects."""
    return {str(o["url"]) for o in objects}


@pytest.mark.core
def test_statussen_in_order(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A new zaak has no status; after two statussen the zaak points at the second (TA reg-15)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    assert not zaak["status"]
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]), "Ingediend door podiumd-tests")
    tweede = make_status(openzaak, zaak, str(parts.statustypen[1]["url"]), "In behandeling genomen")
    assert openzaak.get(str(zaak["url"]))["status"] == tweede["url"]
    assert len(openzaak.list(f"{ZAKEN}/statussen", {"zaak": str(zaak["url"])})) == 2


def test_zaak_closes_with_resultaat_and_eindstatus(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """With a resultaat and the eindstatus the zaak gets an einddatum and an archiefnominatie (TA reg-39, extended)."""
    if not parts.resultaattypen:
        pytest.skip("test zaaktype has no resultaattype (Selectielijst API was unreachable at bootstrap)")
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    openzaak.post(
        f"{ZAKEN}/resultaten",
        {"zaak": zaak["url"], "resultaattype": parts.resultaattypen[0], "toelichting": "afgehandeld"},
    )
    make_status(openzaak, zaak, str(parts.statustypen[-1]["url"]), "Afgehandeld")
    closed = openzaak.get(str(zaak["url"]))
    assert closed["einddatum"]
    assert closed["archiefnominatie"] == "vernietigen"
    assert closed["archiefactiedatum"]


@pytest.mark.xfail(
    strict=True,
    reason="Open Zaak 1.29.3: DELETE of a zaak with a resultaat answers 500 although it deletes the zaak "
    "(vng_api_common etag recalculated for the deleted resultaat); not yet reported upstream",
)
def test_closed_zaak_delete_answers_204(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """Deleting a zaak with a resultaat answers 204."""
    if not parts.resultaattypen:
        pytest.skip("test zaaktype has no resultaattype (Selectielijst API was unreachable at bootstrap)")
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    openzaak.post(f"{ZAKEN}/resultaten", {"zaak": zaak["url"], "resultaattype": parts.resultaattypen[0]})
    openzaak.request("DELETE", str(zaak["url"]), 204)


def test_archiefnominatie_can_be_set_and_filtered(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """archiefnominatie, archiefactiedatum and archiefstatus are stored and filterable (TA reg-39)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    assert zaak["einddatum"] is None
    changed = openzaak.patch(
        str(zaak["url"]),
        {"archiefnominatie": "vernietigen", "archiefactiedatum": "2036-01-01", "archiefstatus": "nog_te_archiveren"},
    )
    assert (changed["archiefnominatie"], changed["archiefactiedatum"]) == ("vernietigen", "2036-01-01")
    found = openzaak.list(f"{ZAKEN}/zaken", {"zaaktype": parts.zaaktype, "archiefnominatie": "vernietigen"})
    assert str(zaak["url"]) in urls(found)


@pytest.mark.core
def test_zaak_found_by_initiator_bsn(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """The initiator's BSN finds the zaak through the list filter and _zoek; another BSN does not (TA int-10, reg-50)."""
    bsn = random_bsn()
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
    assert urls(openzaak.list(f"{ZAKEN}/zaken", {BSN_FILTER: bsn})) == {str(zaak["url"])}
    assert openzaak.list(f"{ZAKEN}/zaken", {BSN_FILTER: random_bsn()}) == []
    zoek = openzaak.request("POST", f"{ZAKEN}/zaken/_zoek", 200, json={BSN_FILTER: bsn}).json()
    assert urls(zoek["results"]) == {str(zaak["url"])}


def test_zoek_finds_each_bsn_only_its_own_zaak(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """For three zaken with their own initiator, _zoek by each BSN finds exactly that zaak (TA reg-56, as a loop)."""
    zaken: dict[str, str] = {}
    for _ in range(3):
        bsn = random_bsn()
        zaak = make_zaak(openzaak, registry, parts.zaaktype)
        make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
        zaken[bsn] = str(zaak["url"])
    for bsn, url in zaken.items():
        zoek = openzaak.request("POST", f"{ZAKEN}/zaken/_zoek", 200, json={BSN_FILTER: bsn}).json()
        assert urls(zoek["results"]) == {url}


@pytest.mark.xfail(
    strict=True,
    reason="Open Zaak 1.29.3: _zoek ignores an unknown filter (e.g. inpBsn__in, which TA reg-56 relied on) and returns "
    "all zaken, where GET /zaken answers 400; not yet reported upstream",
)
def test_zoek_refuses_an_unknown_filter(openzaak: ApiClient) -> None:
    """_zoek with an unsupported filter answers 400, as GET /zaken does."""
    openzaak.request("POST", f"{ZAKEN}/zaken/_zoek", 400, json={f"{BSN_FILTER}__in": [random_bsn()]})


def test_rollen_of_two_kinds(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A burger initiator and a medewerker belanghebbende: both listed, both filters find the zaak (TA reg-41)."""
    bsn = random_bsn()
    medewerker = registry.tagged("mdw")
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
    make_rol(
        openzaak,
        registry,
        zaak,
        parts.roltypen["belanghebbende"],
        "medewerker",
        identificatie=medewerker,
        achternaam="Test",
        voorletters="P",
    )
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": str(zaak["url"])})
    assert sorted(str(r["betrokkeneType"]) for r in rollen) == ["medewerker", "natuurlijk_persoon"]
    by_medewerker = openzaak.list(
        f"{ZAKEN}/zaken", {"rol__betrokkeneIdentificatie__medewerker__identificatie": medewerker}
    )
    assert urls(by_medewerker) == {str(zaak["url"])}


def test_rol_of_a_company(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A niet-natuurlijk persoon with a KvK number finds the zaak (TA reg-16)."""
    kvk = random_kvk_nummer()
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    make_rol(
        openzaak,
        registry,
        zaak,
        parts.roltypen["initiator"],
        "niet_natuurlijk_persoon",
        kvkNummer=kvk,
        statutaireNaam=registry.tagged("bv"),
    )
    found = openzaak.list(f"{ZAKEN}/zaken", {"rol__betrokkeneIdentificatie__nietNatuurlijkPersoon__kvkNummer": kvk})
    assert urls(found) == {str(zaak["url"])}


@pytest.mark.parametrize("machtiging", ["gemachtigde", "machtiginggever"])
def test_rol_indicatie_machtiging(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, machtiging: str
) -> None:
    """indicatieMachtiging is stored on the rol (TA reg-122)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    body = {
        "zaak": zaak["url"],
        "betrokkeneType": "natuurlijk_persoon",
        "roltype": parts.roltypen["initiator"],
        "roltoelichting": registry.tagged("rol"),
        "indicatieMachtiging": machtiging,
        "betrokkeneIdentificatie": {"inpBsn": random_bsn()},
    }
    rol = openzaak.post(f"{ZAKEN}/rollen", body)
    registry.add("rol", lambda: openzaak.delete(str(rol["url"])))
    assert rol["indicatieMachtiging"] == machtiging
