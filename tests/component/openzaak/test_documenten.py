"""Open Zaak documenten: upload, link to a zaak, lock and new versions, signature, integrity.

Ported from TA interaction 03 and regression 49, 51 and 64 (64 covers 49 and 51b).
"""

from __future__ import annotations

import base64
import hashlib

from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_document_in_parts
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


@pytest.mark.source(
    "TA interaction/03-document-koppeling.spec.ts",
    "A document is linked to a zaak in two steps, EnkelvoudigInformatieObject and ZaakInformatieObject, as ZGW prescribes.",
)
@pytest.mark.core
def test_document_linked_to_zaak(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A document linked to a zaak shows in the zaak's zaakinformatieobjecten (TA int-03)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    link_document(openzaak, registry, zaak, document)
    linked = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    assert [z["informatieobject"] for z in entries(linked)] == [document["url"]]


@pytest.mark.source(
    "TA regression/64-document-lifecycle.spec.ts",
    "Document lifecycle: upload, sign, make definitief, add version 2 and unlock.",
)
@pytest.mark.source(
    "TA regression/49-document-download.spec.ts", "A document upload stores the content and its download metadata."
)
@pytest.mark.source(
    "TA regression/51-document-crud-edges.spec.ts",
    "Document edge cases: gebruiksrecht, concept to definitief, ondertekening and integriteit.",
)
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


@pytest.mark.source(
    "TA regression/51-document-crud-edges.spec.ts",
    "Document edge cases: gebruiksrecht, concept to definitief, ondertekening and integriteit.",
)
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
    "[open-zaak-3] Open Zaak 1.29.3: audittrail endpoints check the component 'audittrails' (AuditTrail's app label), "
    "so only clients with heeft_alle_autorisaties can read them; not yet reported upstream"
)


@pytest.mark.source(
    "TA regression/64-document-lifecycle.spec.ts",
    "Document lifecycle: upload, sign, make definitief, add version 2 and unlock.",
)
@pytest.mark.xfail(strict=True, reason=AUDITTRAIL_BUG)
def test_document_audittrail_with_catalogus_rights(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """A client with audittrails.lezen on the catalogus reads a document's audittrail (TA reg-64)."""
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    assert openzaak.request("GET", f"{document['url']}/audittrail", 200).json()


# Concurrent same-name unlocks; four hit the race in every try on minikube.
SAME_NAME_UPLOADS = 4
# Over Open Zaak's in-memory upload limit, so the parts are merged through a file.
LARGE_DOCUMENT = 3_000_000


@pytest.mark.xfail(
    reason="[open-zaak-4] Open Zaak 1.29.3 merges the bestandsdelen of documents with the same bestandsnaam in one"
    " temporary file: concurrent unlocks answer 500 or store another document's content; fixed in 1.31.0"
    " (open-zaak#2592). A race: it may not hit",
)
@pytest.mark.source(
    "upstream open-zaak/open-zaak CHANGELOG.rst",
    "1.31.0, #2592: documents with the same file name saved at the same time overwrote each other's content.",
)
def test_large_documents_with_the_same_name_keep_their_own_content(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """Documents uploaded in parts under one bestandsnaam and unlocked at once each keep their own content."""
    contents = [bytes([ord("A") + i]) * LARGE_DOCUMENT for i in range(SAME_NAME_UPLOADS)]
    name = f"{registry.tagged('deel')}.bin"
    documents = [
        make_document_in_parts(openzaak, registry, parts.informatieobjecttype, c, bestandsnaam=name) for c in contents
    ]

    def unlock(document: JsonObject) -> int:
        body = {"lock": document["lock"]}
        return openzaak.request("POST", f"{document['url']}/unlock", 204, 500, json=body).status_code

    with ThreadPoolExecutor(SAME_NAME_UPLOADS) as pool:
        unlocked = list(pool.map(unlock, documents))
    stored = []
    for document in documents:
        download = openzaak.http.get(f"{document['url']}/download", headers={**openzaak.headers(), "Accept": "*/*"})
        stored.append(download.content if download.status_code == HTTPStatus.OK else b"")
    assert unlocked == [HTTPStatus.NO_CONTENT] * SAME_NAME_UPLOADS
    assert [s == c for s, c in zip(stored, contents, strict=True)] == [True] * SAME_NAME_UPLOADS
