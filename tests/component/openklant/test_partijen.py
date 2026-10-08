"""Open Klant partijen: CRUD, identificators, digital addresses and betrokkenen.

Ported from TA interaction 35 and 145 and regression 54, 58, 85, 86 and 149.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.seed.openklant import expanded
from podiumd_tests.seed.openklant import make_betrokkene
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import make_organisatie
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openklant import random_kvk_nummer

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openklant")]


def test_partij_lifecycle(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """A created partij reads back, accepts a PATCH and is gone after DELETE."""
    partij = make_partij(openklant, registry)
    url = str(partij["url"])
    assert openklant.get(url)["soortPartij"] == "persoon"
    assert openklant.patch(url, {"indicatieActief": False})["indicatieActief"] is False
    openklant.delete(url)
    openklant.request("GET", url, 404)


def test_partij_is_found_by_its_nummer(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """The nummer Open Klant assigns is a working filter."""
    partij = make_partij(openklant, registry)
    found = openklant.list("partijen", {"nummer": str(partij["nummer"])})
    assert [p["url"] for p in found] == [partij["url"]]


def test_contactnaam_is_stored(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """The partij identification comes back as sent."""
    partij = make_partij(openklant, registry)
    identificatie = cast("dict[str, dict[str, str]]", openklant.get(str(partij["url"]))["partijIdentificatie"])
    assert identificatie["contactnaam"]["achternaam"] == registry.tagged("partij")


@pytest.mark.core
def test_persoon_with_bsn_and_email(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """A persoon gets a BSN and an e-mail address; both lookups find them (TA int-35)."""
    partij = make_partij(openklant, registry)
    bsn = random_bsn()
    make_partij_identificator(openklant, registry, partij, "bsn", bsn)
    adres = f"{registry.tagged('mail')}@example.invalid"
    make_digitaal_adres(openklant, registry, partij, adres)
    by_bsn = openklant.list("partij-identificatoren", {"partijIdentificatorObjectId": bsn})
    assert [section(i, "identificeerdePartij").get("uuid") for i in by_bsn] == [partij["uuid"]]
    by_adres = openklant.list("digitaleadressen", {"adres": adres})
    assert [section(a, "verstrektDoorPartij").get("uuid") for a in by_adres] == [partij["uuid"]]


@pytest.mark.parametrize(
    ("kind", "number"), [("kvk_nummer", random_kvk_nummer()), ("rsin", random_bsn())], ids=["kvk", "rsin"]
)
def test_organisatie_identificator(openklant: ApiClient, registry: ResourceRegistry, kind: str, number: str) -> None:
    """An organisatie carries a KvK number or an RSIN (TA reg-85)."""
    partij = make_organisatie(openklant, registry)
    assert partij["soortPartij"] == "organisatie"
    make_partij_identificator(openklant, registry, partij, kind, number)
    found = openklant.list("partij-identificatoren", {"partijIdentificatorObjectId": number})
    assert [section(i, "partijIdentificator").get("codeSoortObjectId") for i in found] == [kind]


def test_digitaal_adres_patch_and_expand(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """A partij's e-mail address shows with expand, changes with PATCH and goes with DELETE (TA reg-58, reg-149)."""
    partij = make_partij(openklant, registry)
    adres = make_digitaal_adres(openklant, registry, partij, f"{registry.tagged('a')}@example.invalid")
    adressen = expanded(openklant, str(partij["url"]), "digitaleAdressen")
    assert [a["uuid"] for a in adressen] == [adres["uuid"]]
    nieuw = f"{registry.tagged('b')}@example.invalid"
    assert openklant.patch(str(adres["url"]), {"adres": nieuw})["adres"] == nieuw
    openklant.delete(str(adres["url"]))
    openklant.request("GET", str(adres["url"]), 404)


def test_betrokkenen_of_a_partij(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """Two klantcontacten of one partij are both found through its betrokkenen (TA reg-54, reg-86, int-145)."""
    partij = make_organisatie(openklant, registry)
    contacten = [make_klantcontact(openklant, registry) for _ in range(2)]
    for klantcontact in contacten:
        make_betrokkene(openklant, registry, klantcontact, partij)
    found = openklant.list("betrokkenen", {"wasPartij__uuid": str(partij["uuid"])})
    assert sorted(str(section(b, "hadKlantcontact").get("uuid")) for b in found) == sorted(
        str(k["uuid"]) for k in contacten
    )
