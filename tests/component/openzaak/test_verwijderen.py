"""Open Zaak deletes: what goes with a zaak, a document or a besluit, and what a link protects.

The audittrail half of drc-008 and brc-009 is left out: reading an audittrail needs heeft_alle_autorisaties on
Open Zaak 1.29.3 (open-zaak-3), which the suite's clients do not have.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openzaak import DOCUMENTEN
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import link_besluit_document
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_besluit
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_gebruiksrechten
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


def objectinformatieobjecten(openzaak: ApiClient, document: JsonObject) -> list[JsonObject]:
    """The objectinformatieobjecten Documenten API keeps for a document."""
    return openzaak.list(f"{DOCUMENTEN}/objectinformatieobjecten", {"informatieobject": str(document["url"])})


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
    status = make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    rol = make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn="999990019")
    body = {"zaak": zaak["url"], "objectType": "overige", "objectTypeOverige": "ptest", "relatieomschrijving": "x"}
    zaakobject = openzaak.post(f"{ZAKEN}/zaakobjecten", {**body, "objectIdentificatie": {"overigeData": {"a": 1}}})
    eigenschap_body = {"zaak": zaak["url"], "eigenschap": parts.eigenschappen["kenteken"], "waarde": "12-AB-34"}
    eigenschap = openzaak.post(f"{zaak['url']}/zaakeigenschappen", eigenschap_body)
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    link = link_document(openzaak, registry, zaak, document)
    delete_zaak(openzaak, str(zaak["url"]))
    gone(openzaak, zaak["url"], status["url"], rol["url"], zaakobject["url"], eigenschap["url"], link["url"])
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
