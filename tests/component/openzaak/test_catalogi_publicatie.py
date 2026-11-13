"""Open Zaak's rules for published catalogus types: what may still change, what may still be added, what publishes.

Every type here is a run-tagged throwaway in the test catalogus; cleanup deletes the published ones with a Django
snippet, since the API refuses that. No request names a bootstrap type: if Open Zaak wrongly accepted a change,
every other test's zaaktype would change.
"""

from __future__ import annotations

import uuid

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import strings
from podiumd_tests.responses import invalid_codes
from podiumd_tests.seed.catalogi import ZaaktypeTypes
from podiumd_tests.seed.catalogi import eigenschap_body
from podiumd_tests.seed.catalogi import make_concept_besluittype
from podiumd_tests.seed.catalogi import make_concept_iot
from podiumd_tests.seed.catalogi import make_publishable_zaaktype
from podiumd_tests.seed.catalogi import publish
from podiumd_tests.seed.catalogi import resultaattype_body
from podiumd_tests.seed.catalogi import template_resultaattype
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import make_concept_zaaktype
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("openzaak", "cluster"),
    pytest.mark.source(
        "external OneGround/ZGW-APIs-postman-tests ZGW business rules ztc-009 to ztc-012",
        "A published type does not change, except its eindeGeldigheid; publishing needs published related types.",
    ),
]

REFUSED_CHANGE = (HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN, HTTPStatus.METHOD_NOT_ALLOWED)


@pytest.fixture(name="published")
def fixture_published(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, selectielijst_zaaktype: JsonObject
) -> JsonObject:
    """Return a throwaway published zaaktype with an eigenschap."""
    types = ZaaktypeTypes(eigenschappen=("kenmerk",))
    return publish(openzaak, make_publishable_zaaktype(podiumd_env, openzaak, registry, selectielijst_zaaktype, types))


def _refused(openzaak: ApiClient, method: str, url: str, body: JsonObject | None = None) -> None:
    openzaak.request(method, url, *REFUSED_CHANGE, json=body or {})


def _refused_as(openzaak: ApiClient, code: str, method: str, url: str, body: JsonObject | None = None) -> None:
    response = openzaak.request(method, url, HTTPStatus.BAD_REQUEST, json=body or {})
    assert invalid_codes(response) == [code], f"{method} {url}: {response.text}"


# The field a PATCH of each child type changes.
CHILD_FIELDS = {
    "statustypen": "omschrijving",
    "roltypen": "omschrijving",
    "eigenschappen": "definitie",
    "resultaattypen": "omschrijving",
}


@pytest.mark.parametrize("kind", ["zaaktype", "besluittype", "informatieobjecttype"])
@pytest.mark.scenario("""
    Given a published zaaktype, besluittype or informatieobjecttype
    When it is replaced, changed or deleted
    Then Open Zaak refuses it
    And only its end of validity may still be set
""")
def test_published_type_changes_only_its_einde_geldigheid(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    selectielijst_zaaktype: JsonObject,
    kind: str,
) -> None:
    """PUT, PATCH and DELETE of a published type are refused; PATCH of eindeGeldigheid alone is accepted."""
    catalogus = str(selectielijst_zaaktype["catalogus"])
    concept = {
        "zaaktype": lambda: make_publishable_zaaktype(podiumd_env, openzaak, registry, selectielijst_zaaktype),
        "besluittype": lambda: make_concept_besluittype(podiumd_env, openzaak, registry, catalogus),
        "informatieobjecttype": lambda: make_concept_iot(podiumd_env, openzaak, registry, catalogus),
    }[kind]()
    published = publish(openzaak, concept)
    url = str(published["url"])
    assert published["concept"] is False
    _refused(openzaak, "PUT", url, {key: value for key, value in published.items() if key != "url"})
    _refused(openzaak, "PATCH", url, {"omschrijving": registry.tagged("gewijzigd")})
    _refused(openzaak, "DELETE", url)
    einde = (datetime.now(tz=UTC).date() + timedelta(days=365)).isoformat()
    changed = openzaak.patch(url, {"eindeGeldigheid": einde})
    assert changed["eindeGeldigheid"] == einde


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rules ztc-010, ztc-011",
    "The types of a published zaaktype cannot change or be added, except a zaaktype-informatieobjecttype.",
)
@pytest.mark.scenario("""
    Given a published zaaktype
    Then its statustype, roltype, eigenschap and resultaattype cannot be changed or deleted
    And no statustype, roltype, eigenschap or resultaattype can be added to it
    But a concept informatieobjecttype can still be linked to it, and the zaaktype then lists it
""")
def test_published_zaaktype_keeps_its_types(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    selectielijst_zaaktype: JsonObject,
    published: JsonObject,
) -> None:
    """Child types of a published zaaktype are fixed; a link to a concept informatieobjecttype is accepted and shows."""
    url = str(published["url"])
    new = {
        "statustypen": {"zaaktype": url, "omschrijving": "Extra", "volgnummer": 3},
        "roltypen": {"zaaktype": url, "omschrijving": "Extra", "omschrijvingGeneriek": "belanghebbende"},
        "eigenschappen": eigenschap_body(url, "extra"),
        "resultaattypen": resultaattype_body(
            url, template_resultaattype(openzaak, selectielijst_zaaktype), omschrijving="Extra"
        ),
    }
    for path, field in CHILD_FIELDS.items():
        child = str(openzaak.list(f"{CATALOGI}/{path}", {"zaaktype": url})[0]["url"])
        _refused_as(openzaak, "non-concept-zaaktype", "PATCH", child, {field: registry.tagged("gewijzigd")})
        _refused_as(openzaak, "non-concept-zaaktype", "DELETE", child)
        _refused_as(openzaak, "non-concept-zaaktype", "POST", f"{CATALOGI}/{path}", new[path])
    # Linking two published types is refused too (non-concept-relation); one side must be a concept.
    iot = make_concept_iot(podiumd_env, openzaak, registry, str(published["catalogus"]))
    ziot = {"zaaktype": url, "informatieobjecttype": iot["url"], "volgnummer": 2, "richting": "inkomend"}
    openzaak.post(f"{CATALOGI}/zaaktype-informatieobjecttypen", ziot)
    assert iot["url"] in strings(openzaak.get(url)["informatieobjecttypen"])


@pytest.mark.source(
    "external VNG-Realisatie/gemma-postman-tests ZGW_api_postman_tests ZGW business rule ztc-011",
    "A type cannot be related to a published type unless one of them is a concept.",
)
@pytest.mark.parametrize("kind", ["besluittype", "zaaktype"])
@pytest.mark.scenario("""
    Given a concept besluittype and a published informatieobjecttype, or a concept zaaktype and a published besluittype
    When the concept is changed to name the published type
    Then Open Zaak refuses it
""")
def test_concept_type_cannot_name_a_published_type(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    selectielijst_zaaktype: JsonObject,
    kind: str,
) -> None:
    """PATCH of a concept besluittype's informatieobjecttypen or zaaktype's besluittypen to a published one is a 400."""
    catalogus = str(selectielijst_zaaktype["catalogus"])
    if kind == "besluittype":
        concept = make_concept_besluittype(podiumd_env, openzaak, registry, catalogus)
        field, related = "informatieobjecttypen", make_concept_iot(podiumd_env, openzaak, registry, catalogus)
    else:
        concept = make_concept_zaaktype(openzaak, registry, catalogus)
        field, related = "besluittypen", make_concept_besluittype(podiumd_env, openzaak, registry, catalogus)
    published = publish(openzaak, related)
    _refused_as(openzaak, "non-concept-relation", "PATCH", str(concept["url"]), {field: [published["url"]]})


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule ztc-012",
    "A zaaktype that names a concept besluittype or informatieobjecttype cannot be published.",
)
@pytest.mark.parametrize("related", ["besluittype", "informatieobjecttype"])
@pytest.mark.scenario("""
    Given a concept zaaktype that names a concept besluittype or informatieobjecttype
    When the zaaktype is published
    Then Open Zaak refuses it
""")
def test_zaaktype_with_a_concept_type_does_not_publish(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    selectielijst_zaaktype: JsonObject,
    related: str,
) -> None:
    """POST publish of a zaaktype related to a concept type answers 400."""
    catalogus = str(selectielijst_zaaktype["catalogus"])
    if related == "besluittype":
        besluittype = make_concept_besluittype(podiumd_env, openzaak, registry, catalogus)
        zaaktype = make_publishable_zaaktype(
            podiumd_env, openzaak, registry, selectielijst_zaaktype, besluittypen=[besluittype["url"]]
        )
    else:
        zaaktype = make_publishable_zaaktype(podiumd_env, openzaak, registry, selectielijst_zaaktype)
        iot = make_concept_iot(podiumd_env, openzaak, registry, catalogus)
        ziot = {
            "zaaktype": zaaktype["url"],
            "informatieobjecttype": iot["url"],
            "volgnummer": 1,
            "richting": "inkomend",
        }
        openzaak.post(f"{CATALOGI}/zaaktype-informatieobjecttypen", ziot)
    response = openzaak.request("POST", f"{zaaktype['url']}/publish", HTTPStatus.BAD_REQUEST, json={})
    assert invalid_codes(response) == ["concept-relation"], response.text


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW features, Geldigheid",
    "Two published versions of one zaaktype cannot be valid on the same day.",
)
@pytest.mark.scenario("""
    Given a published zaaktype valid from today without end
    When a second version with the same identificatie and overlapping validity is published
    Then Open Zaak refuses to publish it
""")
def test_overlapping_published_versions_are_refused(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    selectielijst_zaaktype: JsonObject,
    published: JsonObject,
) -> None:
    """Publishing a second version whose validity overlaps a published one answers 400."""
    second = make_publishable_zaaktype(
        podiumd_env, openzaak, registry, selectielijst_zaaktype, identificatie=published["identificatie"]
    )
    openzaak.request("POST", f"{second['url']}/publish", HTTPStatus.BAD_REQUEST, json={})


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW features, zaakobjecttype",
    "Open Archiefbeheer reads zaakobjecttypen; they change with a concept zaaktype and stay with a published one.",
)
@pytest.mark.scenario("""
    Given a concept zaaktype
    When a zaakobjecttype is added to it, changed and deleted
    Then the zaaktype has it, then the change, then no longer
    When the zaaktype is published with a zaakobjecttype
    Then that zaakobjecttype cannot be deleted
""")
def test_zaakobjecttype_changes_only_with_a_concept_zaaktype(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, selectielijst_zaaktype: JsonObject
) -> None:
    """Zaakobjecttype POST, PATCH and DELETE on a concept zaaktype; DELETE is refused after publishing."""
    zaaktype = make_publishable_zaaktype(podiumd_env, openzaak, registry, selectielijst_zaaktype)
    path = f"{CATALOGI}/zaakobjecttypen"
    # Without status alles the list leaves out the types of a concept zaaktype.
    query = {"zaaktype": str(zaaktype["url"]), "status": "alles"}
    body = {
        "zaaktype": zaaktype["url"],
        # Open Zaak does not fetch the objecttype.
        "objecttype": f"https://objecttypen.example.invalid/api/v2/objecttypes/{uuid.uuid4()}",
        "anderObjecttype": False,
        "relatieOmschrijving": "Betreft",
        "beginGeldigheid": today(),
    }
    created = openzaak.post(path, body)
    url = str(created["url"])
    assert [z["url"] for z in openzaak.list(path, query)] == [url]
    assert openzaak.patch(url, {"relatieOmschrijving": "Gewijzigd"})["relatieOmschrijving"] == "Gewijzigd"
    openzaak.request("DELETE", url, HTTPStatus.NO_CONTENT)
    assert openzaak.list(path, query) == []
    kept = openzaak.post(path, body)
    publish(openzaak, zaaktype)
    _refused(openzaak, "DELETE", str(kept["url"]))
    assert [z["url"] for z in openzaak.list(path, query)] == [kept["url"]]
