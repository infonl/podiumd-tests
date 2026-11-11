"""Open Zaak catalogi: the bootstrap zaaktype's configuration, and concept zaaktypen with versions.

Ported from TA regression 60 and 90 (seed health) and 167 and 173 (zaaktype CRUD and versions);
concept zaaktypen can be deleted, so nothing is left behind.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import make_concept_zaaktype

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


@pytest.mark.source(
    "TA regression/60-seed-data-health.spec.ts",
    "Health check of the bootstrap seed data: catalogus, published zaaktype, statustypen and initiator roltype.",
)
@pytest.mark.source(
    "TA regression/90-fb-oz-catalogi-integriteit.spec.ts",
    "Detects that a chart upgrade or seed error breaks no zaaktype, statustype or informatieobjecttype in the catalogi.",
)
@pytest.mark.scenario("""
    Given the test zaaktype that bootstrap made in Open Zaak
    When its configuration is read
    Then the zaaktype is published and valid without end date
    And its statustypen are numbered 1 to 3 and the last is the eindstatus
    And it has the roltypen initiator, behandelaar and belanghebbende
""")
def test_test_zaaktype_is_published_and_complete(test_zaaktype: JsonObject, parts: ZaaktypeParts) -> None:
    """The bootstrap zaaktype is published, with ordered statustypen ending in an eindstatus and the roles tests use (TA reg-60, 90)."""
    assert test_zaaktype["concept"] is False
    assert test_zaaktype["eindeGeldigheid"] is None
    assert [s["volgnummer"] for s in parts.statustypen] == [1, 2, 3]
    assert parts.statustypen[-1]["isEindstatus"] is True
    assert {"initiator", "behandelaar", "belanghebbende"} <= set(parts.roltypen)


@pytest.mark.source(
    "TA regression/167-fb-zaaktype-crud-api.spec.ts",
    "Functional management can create, version and delete zaaktypen through the Catalogi API.",
)
@pytest.mark.scenario("""
    When a new zaaktype is made in the test catalogus of Open Zaak
    Then the zaaktype is a concept
    And a search for concept zaaktypen with its identificatie finds only this zaaktype
    When the zaaktype is deleted
    Then it is no longer found
""")
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


@pytest.mark.source(
    "TA regression/167-fb-zaaktype-crud-api.spec.ts",
    "Functional management can create, version and delete zaaktypen through the Catalogi API.",
)
@pytest.mark.source(
    "TA regression/173-fb-zaaktype-versie-isolatie.spec.ts",
    "Zaken created under an old zaaktype version stay unchanged when a new version is added.",
)
@pytest.mark.scenario("""
    Given a concept zaaktype valid in the first half of 2026
    When a second version with the same identificatie is made, valid from July 2026
    Then the two versions are separate zaaktypen
    And a search by the identificatie finds both
    And the first version keeps its end of validity
""")
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


@pytest.mark.xfail(
    strict=True,
    raises=UnexpectedStatusError,
    reason="[open-zaak-12] Open Zaak 1.29.3 answers 500 (IntegrityError) to a statustype with a volgnummer the "
    "zaaktype already has; not yet reported upstream",
)
@pytest.mark.source(
    "podiumd-tests",
    "Open Zaak refuses a statustype whose volgnummer the zaaktype already has, as a validation error.",
)
@pytest.mark.scenario("""
    Given a concept zaaktype with a statustype numbered 1
    When a second statustype numbered 1 is added
    Then Open Zaak refuses it as invalid, naming the volgnummer
    And the zaaktype keeps one statustype
""")
def test_duplicate_statustype_volgnummer_is_refused(
    openzaak: ApiClient, registry: ResourceRegistry, test_zaaktype: JsonObject
) -> None:
    """POST /statustypen with a volgnummer the zaaktype already has answers 400, not 500."""
    concept = make_concept_zaaktype(openzaak, registry, str(test_zaaktype["catalogus"]))
    body = {"omschrijving": "podiumd-tests", "zaaktype": concept["url"], "volgnummer": 1}
    openzaak.request("POST", f"{CATALOGI}/statustypen", HTTPStatus.CREATED, json=body)
    refused = openzaak.request("POST", f"{CATALOGI}/statustypen", HTTPStatus.BAD_REQUEST, json=body).json()
    assert refused.get("invalidParams")
    assert len(openzaak.list(f"{CATALOGI}/statustypen", {"zaaktype": str(concept["url"]), "status": "alles"})) == 1
