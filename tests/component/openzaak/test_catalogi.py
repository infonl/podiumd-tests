"""Open Zaak catalogi: the bootstrap zaaktype's configuration, and concept zaaktypen with versions.

Ported from TA regression 60 and 90 (seed health) and 167 and 173 (zaaktype CRUD and versions);
concept zaaktypen can be deleted, so nothing is left behind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import make_concept_zaaktype

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


def test_test_zaaktype_is_published_and_complete(test_zaaktype: JsonObject, parts: ZaaktypeParts) -> None:
    """The bootstrap zaaktype is published, with ordered statustypen ending in an eindstatus and the roles tests use (TA reg-60, 90)."""
    assert test_zaaktype["concept"] is False
    assert test_zaaktype["eindeGeldigheid"] is None
    assert [s["volgnummer"] for s in parts.statustypen] == [1, 2, 3]
    assert parts.statustypen[-1]["isEindstatus"] is True
    assert {"initiator", "behandelaar", "belanghebbende"} <= set(parts.roltypen)


def test_concept_zaaktype_crud(openzaak: ApiClient, registry: ResourceRegistry, test_zaaktype: JsonObject) -> None:
    """A new zaaktype is a concept, is found with status=concept, and can be deleted (TA reg-167)."""
    concept = make_concept_zaaktype(openzaak, registry, str(test_zaaktype["catalogus"]))
    assert concept["concept"] is True
    found = openzaak.list(
        f"{CATALOGI}/zaaktypen", {"identificatie": str(concept["identificatie"]), "status": "concept"}
    )
    assert [z["url"] for z in found] == [concept["url"]]
    openzaak.delete(str(concept["url"]))
    openzaak.request("GET", str(concept["url"]), 404)


def test_zaaktype_versions(openzaak: ApiClient, registry: ResourceRegistry, test_zaaktype: JsonObject) -> None:
    """Two versions with one identificatie and adjacent validity are both kept (TA reg-167, 173)."""
    catalogus = str(test_zaaktype["catalogus"])
    eerste = make_concept_zaaktype(
        openzaak, registry, catalogus, beginGeldigheid="2026-01-01", eindeGeldigheid="2026-06-30"
    )
    tweede = make_concept_zaaktype(
        openzaak,
        registry,
        catalogus,
        identificatie=eerste["identificatie"],
        beginGeldigheid="2026-07-01",
        versiedatum="2026-07-01",
    )
    assert eerste["url"] != tweede["url"]
    found = openzaak.list(f"{CATALOGI}/zaaktypen", {"identificatie": str(eerste["identificatie"]), "status": "concept"})
    assert {str(z["url"]) for z in found} == {str(eerste["url"]), str(tweede["url"])}
    assert openzaak.get(str(eerste["url"]))["eindeGeldigheid"] == "2026-06-30"
