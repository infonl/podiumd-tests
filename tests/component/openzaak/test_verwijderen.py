"""Open Zaak deletes: what goes with a zaak, a document or a besluit, and what a link protects.

Audittrails are read in Open Zaak's database: its API serves them only to clients with heeft_alle_autorisaties
(open-zaak-3), which the suite's clients do not have.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openzaak import audittrail
from podiumd_tests.seed.openzaak import delete_besluit
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import fill_zaak
from podiumd_tests.seed.openzaak import link_besluit_document
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_besluit
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_gebruiksrechten
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import objectinformatieobjecten

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


def gone(openzaak: ApiClient, *urls: object) -> None:
    """Assert that every URL answers 404."""
    for url in urls:
        openzaak.request("GET", str(url), HTTPStatus.NOT_FOUND)


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule zrc-023",
    "Deleting a zaak deletes its status, rol, zaakobject, zaakeigenschap and document links, and their mirror in "
    "Documenten API; the document stays.",
)
@pytest.mark.scenario("""
    Given a zaak with a status, a rol, a zaakobject, an eigenschap and a linked document
    When the zaak is deleted
    Then its status, rol, zaakobject, eigenschap and document link are gone
    And Documenten no longer records the link
    And the document itself remains
""")
def test_deleting_a_zaak_deletes_what_belongs_to_it(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """DELETE of a zaak without resultaat removes its sub-resources and the objectinformatieobject, not the document."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    filled = fill_zaak(openzaak, registry, zaak, parts)
    document = openzaak.get(str(filled["zaakinformatieobjecten"]["informatieobject"]))
    delete_zaak(openzaak, str(zaak["url"]))
    gone(openzaak, zaak["url"], *(sub["url"] for sub in filled.values()))
    assert objectinformatieobjecten(openzaak, document) == []
    openzaak.get(str(document["url"]))


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule drc-008",
    "A document that a zaak still holds cannot be deleted; deleting it deletes its gebruiksrechten.",
)
@pytest.mark.scenario("""
    Given a document with gebruiksrechten, linked to a zaak
    When the document is deleted
    Then Open Zaak refuses while the zaak holds it
    And once the link is removed, deleting the document also deletes its gebruiksrechten
""")
def test_linked_document_cannot_be_deleted(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """DELETE of a document with an objectinformatieobject is a 400; without it, its gebruiksrechten go with it."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    gebruiksrechten = make_gebruiksrechten(openzaak, registry, document)
    link = link_document(openzaak, registry, zaak, document)
    openzaak.request("DELETE", str(document["url"]), HTTPStatus.BAD_REQUEST)
    openzaak.delete(str(link["url"]))
    openzaak.delete(str(document["url"]))
    gone(openzaak, document["url"], gebruiksrechten["url"])


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rules brc-005, brc-009",
    "A besluit-document link is mirrored in Documenten API; deleting the besluit deletes the link and the mirror.",
)
@pytest.mark.xfail(
    strict=True,
    reason="[open-zaak-7] Open Zaak 1.29.3 answers 500 and keeps a besluit of a zaak that holds a document "
    "(ZaakBesluit.DoesNotExist in sync_zaakbesluit); open-zaak#2542, fixed on main by #2594, not yet released",
)
@pytest.mark.scenario("""
    Given a besluit on a zaak with a linked document
    Then Documenten records the link to the besluit
    When the besluit is deleted
    Then the link and its record in Documenten are gone
    And the document itself remains
""")
def test_deleting_a_besluit_deletes_its_document_links(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """DELETE of a besluit removes its besluitinformatieobjecten and their objectinformatieobjecten."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    besluit = make_besluit(openzaak, registry, parts.besluittype, zaak=zaak["url"])
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    link = link_besluit_document(openzaak, registry, besluit, document)
    mirrored = objectinformatieobjecten(openzaak, document)
    assert [(o["object"], o["objectType"]) for o in mirrored] == [(besluit["url"], "besluit")]
    openzaak.delete(str(besluit["url"]))
    gone(openzaak, besluit["url"], link["url"])
    assert objectinformatieobjecten(openzaak, document) == []
    openzaak.get(str(document["url"]))


def _changed_zaak(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> str:
    url = str(make_zaak(openzaak, registry, parts.zaaktype)["url"])
    openzaak.patch(url, {"toelichting": registry.tagged("gewijzigd")})
    return url


def _document_with_gebruiksrechten(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> str:
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    make_gebruiksrechten(openzaak, registry, document)
    return str(document["url"])


def _changed_besluit(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> str:
    url = str(make_besluit(openzaak, registry, parts.besluittype)["url"])
    openzaak.patch(url, {"toelichting": registry.tagged("gewijzigd")})
    return url


def _delete_document(openzaak: ApiClient, url: str) -> None:
    openzaak.delete(url)


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rules drc-008, brc-009",
    "Deleting a document or a besluit deletes its audittrail.",
)
@pytest.mark.source(
    "external VNG-Realisatie/gemma-postman-tests ZGW_OAS_tests BRC besluiten",
    "The audittrail of a besluit records its create and its update.",
)
@pytest.mark.requires("cluster")
@pytest.mark.parametrize(
    ("make", "trail", "delete"),
    [
        pytest.param(_changed_zaak, [("zaak", "create"), ("zaak", "partial_update")], delete_zaak, id="zaak"),
        pytest.param(
            _document_with_gebruiksrechten,
            [("enkelvoudiginformatieobject", "create"), ("gebruiksrechten", "create")],
            _delete_document,
            id="document",
        ),
        pytest.param(
            _changed_besluit, [("besluit", "create"), ("besluit", "partial_update")], delete_besluit, id="besluit"
        ),
    ],
)
@pytest.mark.scenario("""
    Given a changed zaak, a document with gebruiksrechten or a changed besluit
    Then its audittrail records its creation and the change
    When it is deleted
    Then its audittrail is gone too
""")
def test_audittrail_goes_with_the_deleted_object(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    make: Callable[[ApiClient, ResourceRegistry, ZaaktypeParts], str],
    trail: list[tuple[str, str]],
    delete: Callable[[ApiClient, str], None],
) -> None:
    """The audittrail of a zaak, document or besluit holds its create and change, and is empty after its DELETE."""
    url = make(openzaak, registry, parts)
    assert audittrail(podiumd_env, url) == trail
    delete(openzaak, url)
    assert audittrail(podiumd_env, url) == []
