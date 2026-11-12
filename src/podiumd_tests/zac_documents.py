"""Documents of a zaak in ZAC through its REST API: test files, uploads, versions, and ontkoppelde documenten."""

from __future__ import annotations

import io
import json
import zipfile

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries

if TYPE_CHECKING:
    import requests

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# The smallest PDF a viewer opens: one empty page.
MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj"
    b" 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def minimal_docx(text: str, paragraphs: int = 1) -> bytes:
    """Return a Word document with the text in each paragraph, as small as ZAC's office converter still opens."""
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml"'
            ' ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="word/document.xml"'
            ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
            "</Relationships>"
        ),
        "word/document.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' * paragraphs}</w:body></w:document>"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        for name, xml in parts.items():
            docx.writestr(name, xml)
    return buffer.getvalue()


# ZAC checks only the format, not the content; "word" is a real document for the office converter.
FILES = {
    "txt": ("text/plain", b"podiumd-tests"),
    "pdf": ("application/pdf", MINIMAL_PDF),
    "docx": (DOCX, b"versie 1"),
    "eml": (
        "message/rfc822",
        b"From: podiumd-tests@example.invalid\r\nSubject: podiumd-tests\r\n\r\npodiumd-tests\r\n",
    ),
    "word": (DOCX, minimal_docx("podiumd-tests")),
    # About 300 pages: LibreOffice's memory grows with them; gotenberg stops a conversion after 30 s.
    "large-word": (DOCX, minimal_docx("podiumd-tests " * 20, paragraphs=10_000)),
}


def max_file_size_mb(zac: requests.Session, zac_url: str) -> int:
    """Return the largest document upload ZAC allows, in MiB."""
    return int(expect_status(zac.get(f"{zac_url}/rest/configuratie/max-file-size-mb"), HTTPStatus.OK).text)


def document_url(zac_url: str, document: JsonObject) -> str:
    """ZAC's URL of the document."""
    return f"{zac_url}/rest/informatieobjecten/informatieobject/{document['uuid']}"


def _form_field(value: object) -> str:
    """Return a field of ZAC's document form as its UI sends it: an object (taal) as JSON."""
    return json.dumps(value) if isinstance(value, dict) else str(value)


def _file_part(name: str, formaat: str, content: bytes) -> tuple[str, bytes, str]:
    """Return the file part of ZAC's upload form; a .eml goes as application/octet-stream, as ZAC's UI sends it.

    RESTEasy does not read a message/rfc822 part as a file; the formaat field keeps the real type.
    """
    return name, content, "application/octet-stream" if name.endswith(".eml") else formaat


def upload(  # noqa: PLR0913  # the upload form's choices
    zac: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    *,
    extension: str,
    file: tuple[str, bytes],
    status: str = "definitief",
) -> requests.Response:
    """Upload a file (formaat, content) to the zaak as the user does in ZAC; ZAC's answer. Skips without a documenttype.

    The zaak's cleanup deletes the document (delete_zaak with_documents).
    """
    documents = f"{zac_url}/rest/informatieobjecten"
    types = get_entries(zac, f"{documents}/informatieobjecttypes/zaak/{zaak['uuid']}")
    if not types:
        pytest.skip(f"zaaktype {section(zaak, 'zaaktype').get('identificatie')} has no informatieobjecttypen")
    formaat, content = file
    name = f"{registry.tagged('document')}.{extension}"
    form = {
        "titel": name,
        "bestandsnaam": name,
        "formaat": formaat,
        "informatieobjectTypeUUID": str(types[0]["uuid"]),
        # ZAC's enum constant; ZAC 5.9 refuses the API value "openbaar" (500).
        "vertrouwelijkheidaanduiding": "OPENBAAR",
        "status": status,
        "taal": "dut",
        # ZAC parses the format its UI sends: date, hours and minutes, offset.
        "creatiedatum": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M+00:00"),
        "auteur": "podiumd-tests",
    }
    return zac.post(
        f"{documents}/informatieobject/{zaak['uuid']}/{registry.tagged('upload')}",
        params={"taakObject": "false"},
        data=form,
        files={"file": _file_part(name, formaat, content)},
    )


def uploaded_document(  # noqa: PLR0913  # the upload form's choices
    zac: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    *,
    suffix: str = "txt",
    status: str = "definitief",
) -> JsonObject:
    """Upload a document (suffix: a key of FILES) to the zaak with upload; the document."""
    extension = "docx" if suffix.endswith("word") else suffix
    response = upload(zac, zac_url, zaak, registry, extension=extension, file=FILES[suffix], status=status)
    return expect_status(response, HTTPStatus.OK).json()


def nieuwe_versie(  # noqa: PLR0913, PLR0917  # the version form's parts
    zac: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    document: JsonObject,
    fields: JsonObject,
    file: tuple[str, str, bytes] | None = None,
) -> requests.Response:
    """Add a version of the document with these fields and the file (bestandsnaam, formaat, content); ZAC's answer.

    The other fields keep the current version's values, as ZAC's form fills them; taal is one of taal().
    """
    url = document_url(zac_url, document)
    current: JsonObject = expect_status(zac.get(f"{url}/huidigeversie"), HTTPStatus.OK).json()
    form = {**current, **fields}
    parts: dict[str, tuple[str | None, str] | tuple[str, bytes, str]] = {
        name: (None, _form_field(value)) for name, value in form.items() if name not in {"uuid", "bestandsnaam"}
    }
    if file:
        name, formaat, content = file
        parts |= {"bestandsnaam": (None, name), "formaat": (None, formaat), "file": _file_part(name, formaat, content)}
    return zac.put(url, params={"zaak": str(zaak["uuid"])}, files=parts)


def taal(zac: requests.Session, zac_url: str, code: str) -> JsonObject:
    """Return ZAC's taal with this ISO 639-2/B code (dut, eng)."""
    return next(item for item in get_entries(zac, f"{zac_url}/rest/configuratie/talen") if item.get("code") == code)


def zaak_documents(zac: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the documents ZAC lists with the zaak."""
    listed = zac.put(f"{zac_url}/rest/informatieobjecten/informatieobjectenList", json={"zaakUUID": zaak["uuid"]})
    return entries(expect_status(listed, HTTPStatus.OK).json())


# The bron of a document that ZAC moves from its ontkoppelde documenten or its Inbox documenten.
ONTKOPPELDE_DOCUMENTEN = "ontkoppelde-documenten"
INBOX_DOCUMENTEN = "inbox-documenten"


def verplaats_document(
    zac: requests.Session, zac_url: str, document: JsonObject, bron: str, zaak: JsonObject
) -> requests.Response:
    """Move the document from bron (a zaak's identificatie, ONTKOPPELDE_DOCUMENTEN or INBOX_DOCUMENTEN) to the zaak.

    ZAC's answer. A taak's documents are moved with the identificatie of the taak's zaak as bron.
    """
    body = {"documentUUID": document["uuid"], "bron": bron, "nieuweZaakID": zaak["identificatie"]}
    return zac.post(f"{zac_url}/rest/informatieobjecten/informatieobject/verplaats", json=body)


def koppelbare_zaken(
    zac: requests.Session, zac_url: str, zoekterm: str, informatieobjecttype_uuid: object
) -> requests.Response:
    """Search the zaken to move or koppel a document of the informatieobjecttype to; ZAC's answer."""
    body = {
        "zaakIdentificator": zoekterm,
        "informationObjectTypeUuid": informatieobjecttype_uuid,
        "page": 0,
        "rows": 10,
    }
    return zac.put(f"{zac_url}/rest/zoeken/zaken", json=body)


def inbox_documenten(zac: requests.Session, zac_url: str, titel: str) -> list[JsonObject]:
    """Return the entries of ZAC's Inbox documenten whose titel contains titel."""
    listed = zac.put(f"{zac_url}/rest/inboxdocumenten", json={"titel": titel, "page": 0, "maxResults": 100})
    return entries(expect_status(listed, HTTPStatus.OK).json().get("resultaten"))


def ontkoppelde_documenten(zac: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return ZAC's ontkoppelde documenten detached from the zaak."""
    return entries(ontkoppelde_documenten_page(zac, zac_url, zaak, 0, 100).get("resultaten"))


def ontkoppelde_documenten_page(
    zac: requests.Session, zac_url: str, zaak: JsonObject, page: int, max_results: int
) -> JsonObject:
    """Return one page of ZAC's ontkoppelde documenten detached from the zaak, with its totaal."""
    body = {"zaakID": zaak["identificatie"], "page": page, "maxResults": max_results}
    listed = zac.put(f"{zac_url}/rest/ontkoppeldedocumenten", json=body)
    return cast("JsonObject", expect_status(listed, HTTPStatus.OK).json())


def delete_ontkoppeld_document(zac: requests.Session, zac_url: str, ontkoppeld: JsonObject) -> requests.Response:
    """Delete an entry of ZAC's ontkoppelde documenten and its document in Open Zaak; ZAC's answer."""
    return zac.delete(f"{zac_url}/rest/ontkoppeldedocumenten/{ontkoppeld['id']}")


def ontkoppel_document(  # noqa: PLR0913, PLR0917  # the fields of ZAC's request
    zac: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    document: JsonObject,
    reden: str | None,
    registry: ResourceRegistry,
) -> requests.Response:
    """Detach the document from the zaak with a reden (None: sent without); ZAC's answer.

    Cleanup deletes it while it is detached.
    """

    def delete() -> None:
        for ontkoppeld in ontkoppelde_documenten(zac, zac_url, zaak):
            if ontkoppeld.get("documentUUID") == document["uuid"]:
                expect_status(delete_ontkoppeld_document(zac, zac_url, ontkoppeld), HTTPStatus.NO_CONTENT)

    registry.add(f"ontkoppeld document {document['uuid']}", delete)
    body = {"zaakUUID": zaak["uuid"], "documentUUID": document["uuid"]}
    if reden is not None:
        body["reden"] = reden
    return zac.put(f"{zac_url}/rest/zaken/zaakinformatieobjecten/ontkoppel", json=body)
