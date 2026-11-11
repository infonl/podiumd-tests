"""Open Zaak's rules for published catalogus types: what may still change, what may still be added, what publishes.

Every type here is a run-tagged throwaway in the test catalogus; cleanup deletes the published ones with a Django
snippet, since the API refuses that. No request names a bootstrap type: if Open Zaak wrongly accepted a change,
every other test's zaaktype would change.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import strings
from podiumd_tests.seed.catalogi import make_concept_besluittype
from podiumd_tests.seed.catalogi import make_concept_iot
from podiumd_tests.seed.catalogi import make_publishable_zaaktype
from podiumd_tests.seed.catalogi import publish
from podiumd_tests.seed.openzaak import CATALOGI

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


@pytest.fixture(name="template")
def fixture_template(test_zaaktype: JsonObject) -> JsonObject:
    """Return the test zaaktype, when it has the selectielijst procestype publishing needs."""
    if not test_zaaktype.get("selectielijstProcestype"):
        pytest.skip("test zaaktype has no selectielijstProcestype (Selectielijst API was unreachable at bootstrap)")
    return test_zaaktype


@pytest.fixture(name="published")
def fixture_published(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, template: JsonObject
) -> JsonObject:
    """Return a throwaway published zaaktype."""
    return publish(openzaak, make_publishable_zaaktype(podiumd_env, openzaak, registry, template))


def _refused(openzaak: ApiClient, method: str, url: str, body: JsonObject | None = None) -> None:
    openzaak.request(method, url, *REFUSED_CHANGE, json=body or {})


@pytest.mark.parametrize("kind", ["zaaktype", "besluittype", "informatieobjecttype"])
@pytest.mark.scenario("""
    Given a published zaaktype, besluittype or informatieobjecttype
    When it is replaced, changed or deleted
    Then Open Zaak refuses it
    And only its end of validity may still be set
""")
def test_published_type_changes_only_its_einde_geldigheid(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, template: JsonObject, kind: str
) -> None:
    """PUT, PATCH and DELETE of a published type are refused; PATCH of eindeGeldigheid alone is accepted."""
    catalogus = str(template["catalogus"])
    concept = {
        "zaaktype": lambda: make_publishable_zaaktype(podiumd_env, openzaak, registry, template),
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
    Then its statustype and roltype cannot be changed or deleted
    And no statustype or roltype can be added to it
    But a concept informatieobjecttype can still be linked to it, and the zaaktype then lists it
""")
def test_published_zaaktype_keeps_its_types(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, published: JsonObject
) -> None:
    """Child types of a published zaaktype are fixed; a link to a concept informatieobjecttype is accepted and shows."""
    url = str(published["url"])
    statustype = openzaak.list(f"{CATALOGI}/statustypen", {"zaaktype": url})[0]
    roltype = openzaak.list(f"{CATALOGI}/roltypen", {"zaaktype": url})[0]
    for child in (statustype, roltype):
        _refused(openzaak, "PATCH", str(child["url"]), {"omschrijving": registry.tagged("gewijzigd")})
        _refused(openzaak, "DELETE", str(child["url"]))
    _refused(openzaak, "POST", f"{CATALOGI}/statustypen", {"zaaktype": url, "omschrijving": "Extra", "volgnummer": 3})
    rol = {"zaaktype": url, "omschrijving": "Extra", "omschrijvingGeneriek": "belanghebbende"}
    _refused(openzaak, "POST", f"{CATALOGI}/roltypen", rol)
    # Linking two published types is refused too (non-concept-relation); one side must be a concept.
    iot = make_concept_iot(podiumd_env, openzaak, registry, str(published["catalogus"]))
    ziot = {"zaaktype": url, "informatieobjecttype": iot["url"], "volgnummer": 2, "richting": "inkomend"}
    openzaak.post(f"{CATALOGI}/zaaktype-informatieobjecttypen", ziot)
    assert iot["url"] in strings(openzaak.get(url)["informatieobjecttypen"])


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
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, template: JsonObject, related: str
) -> None:
    """POST publish of a zaaktype related to a concept type answers 400."""
    catalogus = str(template["catalogus"])
    if related == "besluittype":
        besluittype = make_concept_besluittype(podiumd_env, openzaak, registry, catalogus)
        zaaktype = make_publishable_zaaktype(
            podiumd_env, openzaak, registry, template, besluittypen=[besluittype["url"]]
        )
    else:
        zaaktype = make_publishable_zaaktype(podiumd_env, openzaak, registry, template)
        iot = make_concept_iot(podiumd_env, openzaak, registry, catalogus)
        ziot = {
            "zaaktype": zaaktype["url"],
            "informatieobjecttype": iot["url"],
            "volgnummer": 1,
            "richting": "inkomend",
        }
        openzaak.post(f"{CATALOGI}/zaaktype-informatieobjecttypen", ziot)
    response = openzaak.request("POST", f"{zaaktype['url']}/publish", HTTPStatus.BAD_REQUEST, json={})
    assert [p["code"] for p in entries(response.json()["invalidParams"])] == ["concept-relation"], response.text


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
    template: JsonObject,
    published: JsonObject,
) -> None:
    """Publishing a second version whose validity overlaps a published one answers 400."""
    second = make_publishable_zaaktype(
        podiumd_env, openzaak, registry, template, identificatie=published["identificatie"]
    )
    openzaak.request("POST", f"{second['url']}/publish", HTTPStatus.BAD_REQUEST, json={})
