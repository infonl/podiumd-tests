"""Open Zaak besluiten on the test zaaktype: a besluit on a zaak, its references, identificatie and documents.

Ported from TA regression 29 and the ZGW business rules brc-001 to brc-008; the besluittypen come from bootstrap,
so no test publishes a type it cannot delete.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.lock import file_lock
from podiumd_tests.responses import invalid_codes
from podiumd_tests.seed.openzaak import BESLUIT_CREATE_LOCK
from podiumd_tests.seed.openzaak import BESLUITEN
from podiumd_tests.seed.openzaak import delete_besluit
from podiumd_tests.seed.openzaak import link_besluit_document
from podiumd_tests.seed.openzaak import make_besluit
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


@pytest.mark.source(
    "TA regression/29-besluit-op-zaak.spec.ts", "A besluit records a formal decision on a zaak in the Besluiten API."
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When a besluit of the zaaktype's besluittype is made on the zaak
    Then the besluit reads back with its besluittype, zaak and toelichting
    And the besluiten of the zaak are only this besluit
""")
def test_besluit_on_a_zaak(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A besluit of the zaak's besluittype reads back and is found by besluittype and zaak (TA reg-29)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    besluit = make_besluit(openzaak, registry, parts.besluittype, zaak=zaak["url"])
    read = openzaak.get(str(besluit["url"]))
    assert (read["besluittype"], read["zaak"], read["toelichting"]) == (
        parts.besluittype,
        zaak["url"],
        registry.tagged("besluit"),
    )
    assert [b["url"] for b in openzaak.list(f"{BESLUITEN}/besluiten", {"zaak": str(zaak["url"])})] == [besluit["url"]]


NOWHERE = "http://openzaak.invalid/catalogi/api/v1/besluittypen/00000000-0000-0000-0000-000000000000"


def _besluit_body(registry: ResourceRegistry, besluittype: str, **fields: object) -> dict[str, object]:
    return {
        "verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN,
        "besluittype": besluittype,
        "datum": today(),
        "ingangsdatum": today(),
        "toelichting": registry.tagged("besluit"),
        **fields,
    }


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rules brc-001, brc-007",
    "A besluit needs a published besluittype that its zaak's zaaktype allows; the besluittype cannot change.",
)
@pytest.mark.parametrize(
    "case",
    [
        "does-not-exist",
        pytest.param(
            "is-a-statustype",
            marks=pytest.mark.xfail(
                strict=True,
                reason="[open-zaak-5] Open Zaak 1.29.3 answers 500 (StatusType has no catalogus in has_auth) for a "
                "client with CatalogusAutorisaties; not yet reported upstream",
            ),
        ),
        "not-of-the-zaaktype",
    ],
)
@pytest.mark.scenario("""
    Given a zaak of the test zaaktype
    When a besluit on it is made with a besluittype that does not exist, is no besluittype or belongs to another zaaktype
    Then Open Zaak refuses the besluit
""")
def test_besluit_needs_a_besluittype_of_the_zaaktype(
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    archief_parts: ZaaktypeParts,
    case: str,
) -> None:
    """POST of a besluit whose besluittype is wrong for its zaak answers 400."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    besluittype = {
        "does-not-exist": NOWHERE,
        "is-a-statustype": str(parts.statustypen[0]["url"]),
        "not-of-the-zaaktype": archief_parts.besluittype,
    }[case]
    body = _besluit_body(registry, besluittype, zaak=zaak["url"])
    response = openzaak.request("POST", f"{BESLUITEN}/besluiten", HTTPStatus.BAD_REQUEST, json=body)
    assert invalid_codes(response), response.text


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rules brc-001, brc-002",
    "A besluit's identificatie is unique per verantwoordelijkeOrganisatie; besluittype, identificatie and "
    "verantwoordelijkeOrganisatie cannot change.",
)
@pytest.mark.scenario("""
    Given two besluiten in Open Zaak
    Then each got its own identificatie
    And a third besluit with the identificatie of the first is refused
    And the besluittype, identificatie and verantwoordelijke organisatie of a besluit cannot change
""")
def test_besluit_identificatie_is_unique_and_fixed(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, archief_parts: ZaaktypeParts
) -> None:
    """Generated identificaties differ, a duplicate is a 400, and PATCH of the fixed fields is a 400."""
    eerste = make_besluit(openzaak, registry, parts.besluittype, identificatie=None)
    tweede = make_besluit(openzaak, registry, parts.besluittype, identificatie=None)
    assert eerste["identificatie"] != tweede["identificatie"]
    body = _besluit_body(registry, parts.besluittype, identificatie=eerste["identificatie"])
    response = openzaak.request("POST", f"{BESLUITEN}/besluiten", HTTPStatus.BAD_REQUEST, json=body)
    assert invalid_codes(response), response.text
    changes = (
        {"besluittype": archief_parts.besluittype},
        {"identificatie": registry.tagged("besluit-id")},
        {"verantwoordelijkeOrganisatie": "111222333"},
    )
    for change in changes:
        response = openzaak.request("PATCH", str(tweede["url"]), HTTPStatus.BAD_REQUEST, json=change)
        assert invalid_codes(response), response.text


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rules brc-003, brc-004, brc-006, brc-008",
    "A besluit holds only existing documents of a type its besluittype allows; the link cannot move; a besluit on "
    "a zaak shows among the zaak's besluiten.",
)
@pytest.mark.scenario("""
    Given a besluit on a zaak
    Then the zaak lists the besluit
    And a document of an informatieobjecttype the besluittype allows can be linked to it
    And a document that does not exist, or of another informatieobjecttype, cannot
    And the link cannot be moved to another besluit or document
""")
def test_besluit_documents_follow_the_besluittype(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, archief_parts: ZaaktypeParts
) -> None:
    """besluitinformatieobjecten: 201 for an allowed type, 400 otherwise, fixed besluit and informatieobject."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    besluit = make_besluit(openzaak, registry, parts.besluittype, zaak=zaak["url"])
    assert [b["besluit"] for b in openzaak.list(f"{zaak['url']}/besluiten")] == [besluit["url"]]
    path = f"{BESLUITEN}/besluitinformatieobjecten"
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    link = link_besluit_document(openzaak, registry, besluit, document)
    vreemd = make_document(openzaak, registry, archief_parts.informatieobjecttype)
    nowhere = NOWHERE.replace("catalogi/api/v1/besluittypen", "documenten/api/v1/enkelvoudiginformatieobjecten")
    for informatieobject in (nowhere, vreemd["url"]):
        body = {"besluit": besluit["url"], "informatieobject": informatieobject}
        response = openzaak.request("POST", path, HTTPStatus.BAD_REQUEST, json=body)
        assert invalid_codes(response), response.text
    tweede = make_besluit(openzaak, registry, parts.besluittype)
    for change in ({"besluit": tweede["url"]}, {"informatieobject": vreemd["url"]}):
        openzaak.request("PATCH", str(link["url"]), HTTPStatus.BAD_REQUEST, HTTPStatus.METHOD_NOT_ALLOWED, json=change)


CONCURRENT_CREATES = 24


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule brc-002",
    "A generated besluit identificatie is unique.",
)
@pytest.mark.xfail(
    strict=True,
    reason="[open-zaak-8] Open Zaak 1.29.3 generates the same identificatie for concurrent besluit creates and "
    "answers 500 (IntegrityError); not yet reported upstream",
)
@pytest.mark.scenario("""
    When 24 besluiten without identificatie are created in Open Zaak at the same time
    Then every create succeeds
    And each besluit has its own identificatie
""")
def test_concurrent_besluiten_get_their_own_identificatie(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """24 parallel creates of besluiten without identificatie all answer 201 with distinct identificaties."""

    def create(_: int) -> requests.Response:
        body = _besluit_body(registry, parts.besluittype)
        response = openzaak.http.post(openzaak.url(f"{BESLUITEN}/besluiten"), json=body, headers=openzaak.headers())
        if response.status_code == HTTPStatus.CREATED:
            url = str(response.json()["url"])
            registry.add(f"besluit {url}", lambda: delete_besluit(openzaak, url))
        return response

    # The lock keeps other workers' besluiten out of this burst; the burst races only with itself.
    with file_lock(BESLUIT_CREATE_LOCK), ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(create, range(CONCURRENT_CREATES)))
    assert all(r.status_code == HTTPStatus.CREATED for r in responses), [r.status_code for r in responses]
    assert len({r.json()["identificatie"] for r in responses}) == CONCURRENT_CREATES
