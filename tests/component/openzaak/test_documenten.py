"""Open Zaak documenten: upload, link to a zaak, lock and new versions, signature, integrity.

Ported from TA interaction 03 and regression 49, 51 and 64 (64 covers 49 and 51b).
"""

from __future__ import annotations

import base64
import hashlib

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


def new_version(openzaak: ApiClient, document: JsonObject, inhoud: str, **fields: object) -> JsonObject:
    """Lock, PUT a new version with inhoud and fields, unlock; the new version."""
    url = str(document["url"])
    lock = openzaak.request("POST", f"{url}/lock", 200, json={}).json()["lock"]
    body = {
        **document,
        **fields,
        "inhoud": base64.b64encode(inhoud.encode()).decode(),
        "bestandsomvang": len(inhoud.encode()),
        "lock": lock,
    }
    for key in ("url", "versie", "beginRegistratie", "locked", "bestandsdelen"):
        body.pop(key, None)
    updated = openzaak.request("PUT", url, 200, json=body).json()
    openzaak.request("POST", f"{url}/unlock", 204, json={"lock": lock})
    return updated


@pytest.mark.core
def test_document_linked_to_zaak(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A document linked to a zaak shows in the zaak's zaakinformatieobjecten (TA int-03)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    link_document(openzaak, registry, zaak, document)
    linked = openzaak.request("GET", f"{ZAKEN}/zaakinformatieobjecten", 200, params={"zaak": str(zaak["url"])}).json()
    assert [z["informatieobject"] for z in entries(linked)] == [document["url"]]


def test_document_versions_and_definitief(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """Version 1 stores the bestandsomvang; lock/PUT/unlock makes it definitief and signed, then version 3 (TA reg-49, 51b, 64)."""
    document = make_document(
        openzaak, registry, parts.informatieobjecttype, inhoud="versie één", indicatieGebruiksrecht=None
    )
    assert (document["versie"], document["bestandsomvang"], document["indicatieGebruiksrecht"]) == (
        1,
        len("versie één".encode()),
        None,
    )
    assert str(document["inhoud"]).endswith("/download?versie=1")
    signed = new_version(
        openzaak, document, "versie één", status="definitief", ondertekening={"soort": "digitaal", "datum": today()}
    )
    assert (signed["versie"], signed["status"]) == (2, "definitief")
    newer = new_version(openzaak, signed, "versie drie")
    assert (newer["versie"], newer["bestandsomvang"]) == (3, len(b"versie drie"))


def test_document_integriteit_and_ondertekening(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """integriteit (sha_256) and ondertekening are stored as sent (TA reg-51c, 51d)."""
    integriteit = {"algoritme": "sha_256", "waarde": hashlib.sha256(b"podiumd-tests").hexdigest(), "datum": today()}
    ondertekening = {"soort": "digitaal", "datum": today()}
    document = make_document(
        openzaak, registry, parts.informatieobjecttype, integriteit=integriteit, ondertekening=ondertekening
    )
    assert (document["integriteit"], document["ondertekening"]) == (integriteit, ondertekening)


AUDITTRAIL_BUG = (
    "Open Zaak 1.29.3: audittrail endpoints check the component 'audittrails' (AuditTrail's app label), "
    "so only clients with heeft_alle_autorisaties can read them; not yet reported upstream"
)


@pytest.mark.xfail(strict=True, reason=AUDITTRAIL_BUG)
def test_document_audittrail_with_catalogus_rights(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """A client with audittrails.lezen on the catalogus reads a document's audittrail (TA reg-64)."""
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    assert openzaak.request("GET", f"{document['url']}/audittrail", 200).json()
