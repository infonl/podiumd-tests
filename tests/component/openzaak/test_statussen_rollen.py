"""Open Zaak statussen, rollen and closing a zaak.

Ported from TA interaction 10 and regression 15, 16, 39, 41, 50, 56 and 122; closing with
a resultaat and the eindstatus is new (TA's seed had no resultaattype).
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openklant import random_kvk_nummer
from podiumd_tests.seed.openzaak import BSN_FILTER
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import close_zaak
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


def urls(objects: list[JsonObject]) -> set[str]:
    """The urls of a list of objects."""
    return {str(o["url"]) for o in objects}


@pytest.mark.source(
    "TA regression/15-status-transitions.spec.ts",
    "A zaak moves through its statussen from Ingediend to Afgehandeld, as ZAC and behandelaars use them.",
)
@pytest.mark.core
@pytest.mark.scenario("""
    When a zaak is made in Open Zaak
    Then the zaak has no status
    When it gets the first two statussen of its zaaktype
    Then the zaak's status is the second
    And the zaak has two statussen
""")
def test_statussen_in_order(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A new zaak has no status; after two statussen the zaak points at the second (TA reg-15)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    assert not zaak["status"]
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]), "Ingediend door podiumd-tests")
    tweede = make_status(openzaak, zaak, str(parts.statustypen[1]["url"]), "In behandeling genomen")
    assert openzaak.get(str(zaak["url"]))["status"] == tweede["url"]
    assert len(openzaak.list(f"{ZAKEN}/statussen", {"zaak": str(zaak["url"])})) == 2


@pytest.mark.source(
    "TA regression/39-zaak-lifecycle-close.spec.ts", "A zaak closes with an einddatum and an archiefnominatie."
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When it gets a resultaat and the eindstatus
    Then the zaak has an einddatum
    And its archiefnominatie is vernietigen
    And its archiefactiedatum is 3650 days after the einddatum
""")
def test_zaak_closes_with_resultaat_and_eindstatus(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """With a resultaat and the eindstatus the zaak gets an einddatum and an archiefnominatie (TA reg-39, extended)."""
    if not parts.resultaattypen:
        pytest.skip("test zaaktype has no resultaattype (Selectielijst API was unreachable at bootstrap)")
    closed = close_zaak(openzaak, make_zaak(openzaak, registry, parts.zaaktype), parts)
    assert closed["einddatum"]
    assert closed["archiefnominatie"] == "vernietigen"
    # The test zaaktype's resultaattype: afleidingswijze afgehandeld, archiefactietermijn 3650 days.
    einddatum = date.fromisoformat(str(closed["einddatum"]))
    assert closed["archiefactiedatum"] == (einddatum + timedelta(days=3650)).isoformat()


@pytest.mark.source("podiumd-tests", "Deleting a zaak with a resultaat must answer 204; Open Zaak 1.29.3 answers 500.")
@pytest.mark.xfail(
    strict=True,
    reason="[open-zaak-1] Open Zaak 1.29.3: DELETE of a zaak with a resultaat answers 500 although it deletes the zaak "
    "(vng_api_common etag recalculated for the deleted resultaat); open-zaak#2484, fixed in 1.31.0",
)
@pytest.mark.scenario("""
    Given a zaak with a resultaat in Open Zaak
    When the zaak is deleted
    Then Open Zaak reports the delete as successful
""")
def test_closed_zaak_delete_answers_204(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """Deleting a zaak with a resultaat answers 204."""
    if not parts.resultaattypen:
        pytest.skip("test zaaktype has no resultaattype (Selectielijst API was unreachable at bootstrap)")
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    openzaak.post(f"{ZAKEN}/resultaten", {"zaak": zaak["url"], "resultaattype": parts.resultaattypen[0]})
    openzaak.request("DELETE", str(zaak["url"]), 204)


@pytest.mark.source(
    "TA regression/39-zaak-lifecycle-close.spec.ts", "A zaak closes with an einddatum and an archiefnominatie."
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak without einddatum
    When its archiefnominatie is set to vernietigen with an archiefactiedatum and an archiefstatus
    Then the zaak holds that archiefnominatie and archiefactiedatum
    And a search for zaken of the zaaktype to be destroyed finds the zaak
""")
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


@pytest.mark.source(
    "TA interaction/10-cross-component-zaak-portaal.spec.ts",
    "The portal and KISS find a resident's zaken through Open Zaak's initiator BSN rol filter.",
)
@pytest.mark.source(
    "TA regression/50-zaak-zoeken.spec.ts",
    "Open Zaak's _zoek endpoint finds a zaak by the initiator's BSN, as KISS uses it.",
)
@pytest.mark.source(
    "TA regression/56-zaak-rel-batch.spec.ts", "KISS finds the zaken of a batch of BSNs with one _zoek call."
)
@pytest.mark.core
@pytest.mark.scenario("""
    Given three zaken in Open Zaak, each with an initiator with their own BSN
    When the zaken are searched by each initiator's BSN, through the list and through the search endpoint
    Then each search finds only that initiator's zaak
    And a search by another BSN finds no zaak
""")
def test_zaak_found_by_initiator_bsn(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """Each initiator's BSN finds only its zaak, by list filter and _zoek; another finds none (TA int-10, reg-50, 56)."""
    zaken: dict[str, str] = {}
    for _ in range(3):
        bsn = random_bsn()
        zaak = make_zaak(openzaak, registry, parts.zaaktype)
        make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
        zaken[bsn] = str(zaak["url"])
    for bsn, url in zaken.items():
        assert urls(openzaak.list(f"{ZAKEN}/zaken", {BSN_FILTER: bsn})) == {url}
        zoek = openzaak.request("POST", f"{ZAKEN}/zaken/_zoek", 200, json={BSN_FILTER: bsn}).json()
        assert urls(zoek["results"]) == {url}
    assert openzaak.list(f"{ZAKEN}/zaken", {BSN_FILTER: random_bsn()}) == []


@pytest.mark.source(
    "TA regression/56-zaak-rel-batch.spec.ts", "KISS finds the zaken of a batch of BSNs with one _zoek call."
)
@pytest.mark.xfail(
    strict=True,
    reason="[open-zaak-2] Open Zaak 1.29.3: _zoek ignores an unknown filter (e.g. inpBsn__in, which TA reg-56 relied on) and returns "
    "all zaken, where GET /zaken answers 400; not yet reported upstream",
)
@pytest.mark.scenario("""
    When the zaken search endpoint of Open Zaak gets a filter it does not support
    Then Open Zaak refuses the search as invalid, as the zaken list does
""")
def test_zoek_refuses_an_unknown_filter(openzaak: ApiClient) -> None:
    """_zoek with an unsupported filter answers 400, as GET /zaken does."""
    openzaak.request("POST", f"{ZAKEN}/zaken/_zoek", 400, json={f"{BSN_FILTER}__in": [random_bsn()]})


@pytest.mark.source(
    "TA regression/41-multi-rollen-zaak.spec.ts",
    "A zaak has several rollen at once and is found through each rol type.",
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When a citizen is added as initiator and an employee as belanghebbende
    Then the zaak's rollen are a natuurlijk persoon and a medewerker
    And a search by the employee's identificatie finds only this zaak
""")
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


@pytest.mark.source(
    "TA regression/16-bedrijf-aanvraag-kvk.spec.ts",
    "A company files a request: the zaak with a niet-natuurlijk persoon rol is found by its KvK number.",
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When a company with a KvK number is added as initiator
    Then a search by that KvK number finds only this zaak
""")
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


@pytest.mark.source(
    "TA regression/122-gemachtigde-flow.spec.ts", "A rol stores indicatieMachtiging for the portal's gemachtigde flow."
)
@pytest.mark.parametrize("machtiging", ["gemachtigde", "machtiginggever"])
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When a citizen is added as initiator with an indicatieMachtiging (gemachtigde or machtiginggever)
    Then the rol holds that indicatieMachtiging
""")
def test_rol_indicatie_machtiging(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, machtiging: str
) -> None:
    """indicatieMachtiging is stored on the rol (TA reg-122)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    initiator = parts.roltypen["initiator"]
    rol = make_rol(openzaak, registry, zaak, initiator, "natuurlijk_persoon", machtiging, inpBsn=random_bsn())
    assert rol["indicatieMachtiging"] == machtiging


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW features, ZRC zaak maken en wijzigen, ZRC rollen",
    "A rol can name a vestiging, a medewerker or an organisatorische eenheid, and the zaak is found by it.",
)
@pytest.mark.parametrize(
    ("betrokkene_type", "generiek", "filter_key", "key", "extra"),
    [
        ("vestiging", "initiator", "vestiging__vestigingsNummer", "vestigingsNummer", {"handelsnaam": ["ptest"]}),
        ("medewerker", "behandelaar", "medewerker__identificatie", "identificatie", {"achternaam": "Test"}),
        (
            "organisatorische_eenheid",
            "behandelaar",
            "organisatorischeEenheid__identificatie",
            "identificatie",
            {"naam": "ptest"},
        ),
    ],
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When a vestiging, a medewerker or an organisatorische eenheid is added to it as a rol
    Then the zaak is found by that betrokkene's identificatie
""")
def test_rol_of_each_betrokkene_type_finds_the_zaak(  # parametrized rol kind
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    betrokkene_type: str,
    generiek: str,
    filter_key: str,
    key: str,
    extra: dict[str, object],
) -> None:
    """A rol of this betrokkeneType stores its identificatie, and the zaken filter on it finds only the zaak."""
    nummer = random_kvk_nummer()[:8] if betrokkene_type == "vestiging" else registry.tagged(betrokkene_type)[:24]
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    make_rol(openzaak, registry, zaak, parts.roltypen[generiek], betrokkene_type, "", **{key: nummer, **extra})
    found = openzaak.list(f"{ZAKEN}/zaken", {f"rol__betrokkeneIdentificatie__{filter_key}": nummer})
    assert urls(found) == {str(zaak["url"])}
