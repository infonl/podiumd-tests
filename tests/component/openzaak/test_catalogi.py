"""Open Zaak catalogi: the bootstrap zaaktype's configuration, concept zaaktypen with versions, Selectielijst links.

Ported from TA regression 60 and 90 (seed health) and 167 and 173 (zaaktype CRUD and versions);
concept zaaktypen can be deleted, so nothing is left behind.
"""

from __future__ import annotations

import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import invalid_codes
from podiumd_tests.responses import invalid_names
from podiumd_tests.seed.catalogi import resultaattype_body
from podiumd_tests.seed.catalogi import template_resultaattype
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import make_concept_zaaktype
from podiumd_tests.seed.openzaak import zaaktype_body

if TYPE_CHECKING:
    import requests

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
    And a search on a date finds only the version valid on that date
    And the first version is not found on a date after its validity
""")
def test_zaaktype_versions(openzaak: ApiClient, registry: ResourceRegistry, test_zaaktype: JsonObject) -> None:
    """Two versions with one identificatie and adjacent validity are kept; datumGeldigheid selects one (TA reg-167, 173)."""
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
    for datum, geldig in (("2026-03-01", eerste), ("2026-08-01", tweede)):
        query = {"identificatie": str(eerste["identificatie"]), "status": "concept", "datumGeldigheid": datum}
        assert [z["url"] for z in openzaak.list(f"{CATALOGI}/zaaktypen", query)] == [geldig["url"]]
    openzaak.get(str(eerste["url"]), {"datumGeldigheid": "2026-03-01"})
    openzaak.request("GET", str(eerste["url"]), HTTPStatus.NOT_FOUND, params={"datumGeldigheid": "2026-08-01"})


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule ztc-001",
    "Open Zaak checks a zaaktype's selectielijstProcestype in the Selectielijst API it is linked to.",
)
@pytest.mark.parametrize(("wrong", "code"), [("resultaat", "invalid-resource"), ("unknown", "bad-url")])
@pytest.mark.scenario("""
    When a zaaktype is made whose selectielijst procestype is a selectielijst resultaat or an unknown procestype
    Then Open Zaak refuses it, naming the selectielijst procestype
""")
def test_zaaktype_selectielijst_procestype_must_be_a_procestype(
    openzaak: ApiClient, registry: ResourceRegistry, selectielijst_zaaktype: JsonObject, wrong: str, code: str
) -> None:
    """POST /zaaktypen with a selectielijstProcestype that is no procestype in the Selectielijst API answers 400."""
    procestype = str(selectielijst_zaaktype["selectielijstProcestype"])
    url = {
        "resultaat": str(template_resultaattype(openzaak, selectielijst_zaaktype)["selectielijstklasse"]),
        "unknown": _unknown(procestype),
    }[wrong]
    body = zaaktype_body(registry, str(selectielijst_zaaktype["catalogus"]), selectielijstProcestype=url)
    response = openzaak.request("POST", f"{CATALOGI}/zaaktypen", HTTPStatus.BAD_REQUEST, json=body)
    assert invalid_codes(response) == [code], response.text
    assert invalid_names(response) == {"selectielijstProcestype"}


def _unknown(url: str) -> str:
    """Return the URL of the same collection with a uuid no resource has."""
    return f"{url.rsplit('/', 1)[0]}/{uuid.UUID(int=0)}"


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule ztc-002",
    "A resultaattype takes omschrijvingGeneriek, archiefnominatie and archiefactietermijn from the Selectielijst.",
)
@pytest.mark.scenario("""
    Given a concept zaaktype with a selectielijst procestype
    When a resultaattype is added with only a selectielijst resultaat and a generic resultaat description
    Then its generic description is that of the Selectielijst
    And its archiefnominatie and archiefactietermijn are the selectielijst resultaat's waardering and bewaartermijn
""")
def test_resultaattype_takes_its_defaults_from_the_selectielijst(
    http: requests.Session, openzaak: ApiClient, registry: ResourceRegistry, selectielijst_zaaktype: JsonObject
) -> None:
    """omschrijvingGeneriek, archiefnominatie and archiefactietermijn left out come from the Selectielijst API."""
    selectielijst = template_resultaattype(openzaak, selectielijst_zaaktype)
    zaaktype = _selectielijst_concept(openzaak, registry, selectielijst_zaaktype)
    created = openzaak.post(f"{CATALOGI}/resultaattypen", resultaattype_body(str(zaaktype["url"]), selectielijst))
    omschrijving = expect_status(http.get(str(selectielijst["resultaattypeomschrijving"])), HTTPStatus.OK).json()
    klasse = expect_status(http.get(str(selectielijst["selectielijstklasse"])), HTTPStatus.OK).json()
    assert (created["omschrijvingGeneriek"], created["archiefnominatie"], created["archiefactietermijn"]) == (
        omschrijving["omschrijving"],
        klasse["waardering"],
        klasse["bewaartermijn"],
    )


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule ztc-002",
    "Open Zaak refuses a resultaattype whose Selectielijst URLs point to the wrong kind of resource or to none.",
)
@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("resultaattypeomschrijving", "selectielijstklasse"),
        ("selectielijstklasse", "resultaattypeomschrijving"),
        ("selectielijstklasse", "unknown"),
    ],
)
@pytest.mark.scenario("""
    Given a concept zaaktype with a selectielijst procestype
    When a resultaattype is added whose Selectielijst link is of the wrong kind or leads nowhere
    Then Open Zaak refuses it, naming that link
""")
def test_resultaattype_selectielijst_urls_are_checked(
    openzaak: ApiClient, registry: ResourceRegistry, selectielijst_zaaktype: JsonObject, field: str, wrong: str
) -> None:
    """POST /resultaattypen with a Selectielijst URL of another kind, or of no resource, answers 400 naming it."""
    selectielijst = template_resultaattype(openzaak, selectielijst_zaaktype)
    zaaktype = _selectielijst_concept(openzaak, registry, selectielijst_zaaktype)
    url = _unknown(str(selectielijst[field])) if wrong == "unknown" else selectielijst[wrong]
    body = resultaattype_body(str(zaaktype["url"]), selectielijst, **{field: url})
    response = openzaak.request("POST", f"{CATALOGI}/resultaattypen", HTTPStatus.BAD_REQUEST, json=body)
    assert invalid_names(response) == {field}, response.text


def _selectielijst_concept(openzaak: ApiClient, registry: ResourceRegistry, template: JsonObject) -> JsonObject:
    procestype = template["selectielijstProcestype"]
    return make_concept_zaaktype(openzaak, registry, str(template["catalogus"]), selectielijstProcestype=procestype)


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
