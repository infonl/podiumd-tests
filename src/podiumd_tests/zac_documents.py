"""Documents of a zaak in ZAC through its REST API: test files, uploads, versions, and ontkoppelde documenten."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from datetime import UTC
from datetime import date
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries

if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Sequence

    import requests

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# The smallest PDF a viewer opens: one empty page.
MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj"
    b" 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


OPENXML = "http://schemas.openxmlformats.org"
RELATIONSHIPS = f"{OPENXML}/officeDocument/2006/relationships"
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'


def _relationships(targets: Sequence[tuple[str, str]]) -> str:
    """Return a relationships part of the targets (relationship type, target), as rId1, rId2, ..."""
    found = "".join(
        f'<Relationship Id="rId{number}" Type="{RELATIONSHIPS}/{kind}" Target={target!r}/>'
        for number, (kind, target) in enumerate(targets, start=1)
    )
    return f'{XML_DECLARATION}<Relationships xmlns="{OPENXML}/package/2006/relationships">{found}</Relationships>'


def _office_file(main: tuple[str, str, str], *related: tuple[str, str, str, str]) -> bytes:
    """Return an Office Open XML file of its main part (path, kind, xml) and the parts it relates to (path, kind,
    relationship type, xml); kind is the content type after application/vnd.openxmlformats-officedocument.
    """
    path, _, xml = main
    folder, _, name = path.rpartition("/")
    overrides = "".join(
        f'<Override PartName="/{part}" ContentType="application/vnd.openxmlformats-officedocument.{kind}"/>'
        for part, kind, *_ in (main, *related)
    )
    parts = {
        "[Content_Types].xml": (
            f'{XML_DECLARATION}<Types xmlns="{OPENXML}/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="xml" ContentType="application/xml"/>{overrides}</Types>'
        ),
        "_rels/.rels": _relationships([("officeDocument", path)]),
        f"{folder}/_rels/{name}.rels": _relationships(
            [(kind, part.removeprefix(f"{folder}/")) for part, _, kind, _ in related]
        ),
        path: f"{XML_DECLARATION}{xml}",
        **{part: f"{XML_DECLARATION}{part_xml}" for part, _, _, part_xml in related},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for part, content in parts.items():
            package.writestr(part, content)
    return buffer.getvalue()


def minimal_docx(text: str, paragraphs: int = 1) -> bytes:
    """Return a Word document with the text in each paragraph, as small as ZAC's office converter still opens."""
    body = f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" * paragraphs
    xml = f'<w:document xmlns:w="{OPENXML}/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    return _office_file(("word/document.xml", "wordprocessingml.document.main+xml", xml))


def minimal_xlsx(text: str) -> bytes:
    """Return an Excel workbook with the text in cell A1 of its one sheet."""
    main = f"{OPENXML}/spreadsheetml/2006/main"
    workbook = (
        f"<workbook xmlns={main!r} xmlns:r={RELATIONSHIPS!r}>"
        '<sheets><sheet name="Blad1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    cell = f'<c r="A1" t="inlineStr"><is><t>{text}</t></is></c>'
    sheet = f'<worksheet xmlns={main!r}><sheetData><row r="1">{cell}</row></sheetData></worksheet>'
    return _office_file(
        ("xl/workbook.xml", "spreadsheetml.sheet.main+xml", workbook),
        ("xl/worksheets/sheet1.xml", "spreadsheetml.worksheet+xml", "worksheet", sheet),
    )


def minimal_pptx(text: str) -> bytes:
    """Return a PowerPoint presentation with the text on its one slide."""
    namespaces = f'xmlns:a="{OPENXML}/drawingml/2006/main" xmlns:p="{OPENXML}/presentationml/2006/main"'
    presentation = (
        f'<p:presentation {namespaces} xmlns:r={RELATIONSHIPS!r}><p:sldIdLst><p:sldId id="256" r:id="rId1"/>'
        '</p:sldIdLst><p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
    )
    shape = (
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Tekst"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>'
        '<a:xfrm><a:off x="0" y="0"/><a:ext cx="9144000" cy="1000000"/></a:xfrm></p:spPr>'
        f"<p:txBody><a:bodyPr/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>"
    )
    group = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
    slide = f"<p:sld {namespaces}><p:cSld><p:spTree>{group}{shape}</p:spTree></p:cSld></p:sld>"
    return _office_file(
        ("ppt/presentation.xml", "presentationml.presentation.main+xml", presentation),
        ("ppt/slides/slide1.xml", "presentationml.slide+xml", "slide", slide),
    )


# ZAC checks only the format, not the content; "word", "excel" and "powerpoint" are real ones for the office converter.
FILES = {
    "txt": ("text/plain", b"podiumd-tests"),
    "pdf": ("application/pdf", MINIMAL_PDF),
    "docx": (DOCX, b"versie 1"),
    "eml": (
        "message/rfc822",
        b"From: podiumd-tests@example.invalid\r\nSubject: podiumd-tests\r\n\r\npodiumd-tests\r\n",
    ),
    "word": (DOCX, minimal_docx("podiumd-tests")),
    "excel": (XLSX, minimal_xlsx("podiumd-tests")),
    "powerpoint": (PPTX, minimal_pptx("podiumd-tests")),
    # About 300 pages: LibreOffice's memory grows with them; gotenberg stops a conversion after 30 s.
    "large-word": (DOCX, minimal_docx("podiumd-tests " * 20, paragraphs=10_000)),
}

# The extension of a file of FILES whose key is no extension.
EXTENSIONS = {"word": "docx", "large-word": "docx", "excel": "xlsx", "powerpoint": "pptx"}


def max_file_size_mb(zac: requests.Session, zac_url: str) -> int:
    """Return the largest document upload ZAC allows, in MiB."""
    return int(expect_status(zac.get(f"{zac_url}/rest/configuratie/max-file-size-mb"), HTTPStatus.OK).text)


def document_url(zac_url: str, document: JsonObject) -> str:
    """ZAC's URL of the document."""
    return f"{zac_url}/rest/informatieobjecten/informatieobject/{document['uuid']}"


def delete_document(http: requests.Session, zac_url: str, zaak: JsonObject, document: JsonObject) -> requests.Response:
    """Delete the zaak's document with a reden; ZAC's answer."""
    return http.delete(document_url(zac_url, document), json={"zaakUuid": zaak["uuid"], "reden": "podiumd-tests"})


def unlock_document(http: requests.Session, zac_url: str, zaak: JsonObject, document: JsonObject) -> requests.Response:
    """Unlock the zaak's document; ZAC's answer."""
    return http.post(f"{document_url(zac_url, document)}/unlock", params={"zaak": str(zaak["uuid"])})


# A conversion of a large document through ZAC's office converter (gotenberg).
CONVERT_TIMEOUT = 60


def convert_to_pdf(http: requests.Session, zac_url: str, zaak: JsonObject, document: JsonObject) -> requests.Response:
    """Convert the zaak's document to a PDF version; ZAC's answer."""
    url = f"{document_url(zac_url, document)}/convert"
    return http.post(url, params={"zaak": str(zaak["uuid"])}, timeout=CONVERT_TIMEOUT)


def lock_document(
    http: requests.Session, zac_url: str, zaak: JsonObject, document: JsonObject, registry: ResourceRegistry
) -> None:
    """Lock the zaak's document as the session's user; cleanup unlocks it, before the zaak's cleanup deletes it.

    ZAC refuses that unlock once the test unlocked the document itself.
    """
    response = http.post(f"{document_url(zac_url, document)}/lock", params={"zaak": str(zaak["uuid"])})
    expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    registry.add(f"lock of document {document['uuid']}", lambda: unlock_document(http, zac_url, zaak, document))


def _form_field(value: object) -> str:
    """Return a field of ZAC's document form as its UI sends it: an object (taal) as JSON."""
    return json.dumps(value) if isinstance(value, dict) else str(value)


def _file_part(name: str, formaat: str, content: bytes) -> tuple[str, bytes, str]:
    """Return the file part of ZAC's upload form; a .eml goes as application/octet-stream, as ZAC's UI sends it.

    RESTEasy does not read a message/rfc822 part as a file; the formaat field keeps the real type.
    """
    return name, content, "application/octet-stream" if name.endswith(".eml") else formaat


def documenttypen(zac: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the documenttypen ZAC offers for a document of the zaak."""
    return get_entries(zac, f"{zac_url}/rest/informatieobjecten/informatieobjecttypes/zaak/{zaak['uuid']}")


def _upload_form(  # noqa: PLR0913, PLR0917  # the zaak, the cleanup, the file and the taak
    zac: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    name: str,
    formaat: str,
    taak: JsonObject | None = None,
) -> tuple[str, dict[str, str]]:
    """Return the URL and the fields of ZAC's upload of a definitief file to the zaak or its taak.

    Skips without a documenttype.
    """
    documents = f"{zac_url}/rest/informatieobjecten"
    types = documenttypen(zac, zac_url, zaak)
    if not types:
        pytest.skip(f"zaaktype {section(zaak, 'zaaktype').get('identificatie')} has no informatieobjecttypen")
    form = {
        "titel": name,
        "bestandsnaam": name,
        "formaat": formaat,
        "informatieobjectTypeUUID": str(types[0]["uuid"]),
        # ZAC's enum constant; ZAC 5.9 refuses the API value "openbaar" (500).
        "vertrouwelijkheidaanduiding": "OPENBAAR",
        "status": "definitief",
        "taal": "dut",
        "creatiedatum": form_date(datetime.now(tz=UTC).date()),
        "auteur": "podiumd-tests",
    }
    reference = str(taak["id"]) if taak else registry.tagged("upload")
    return f"{documents}/informatieobject/{zaak['uuid']}/{reference}?taakObject={str(taak is not None).lower()}", form


def form_date(day: date) -> str:
    """Return the day as ZAC parses a date of its document form: the format its UI sends, with time and offset."""
    return f"{day.isoformat()}T00:00+00:00"


def upload(  # noqa: PLR0913  # the upload form's choices
    zac: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    *,
    extension: str,
    file: tuple[str, bytes],
    taak: JsonObject | None = None,
    **fields: str,
) -> requests.Response:
    """Upload a file (formaat, content) to the zaak as the user does in ZAC, fields replacing the form's; ZAC's answer.

    With a taak, as from that open taak: ZAC adds the document to its taakdocumenten. Skips without a documenttype.
    The zaak's cleanup deletes the document (delete_zaak with_documents).
    """
    formaat, content = file
    name = f"{registry.tagged('document')}.{extension}"
    url, form = _upload_form(zac, zac_url, zaak, registry, name, formaat, taak)
    return zac.post(url, data=form | fields, files={"file": _file_part(name, formaat, content)})


# A streamed upload sends its file in parts of this size.
CHUNK = 1024 * 1024
# A streamed upload of ZAC's largest file through the platform's edge.
UPLOAD_TIMEOUT = 600


def upload_of_size(
    zac: requests.Session, zac_url: str, zaak: JsonObject, registry: ResourceRegistry, size: int
) -> requests.Response:
    """Upload a text file of size bytes to the zaak, streamed so the test never holds it; ZAC's answer."""
    name = f"{registry.tagged('document')}.txt"
    url, form = _upload_form(zac, zac_url, zaak, registry, name, "text/plain")
    boundary = uuid.uuid4().hex
    parts = [f"name={json.dumps(field)}\r\n\r\n{value}\r\n" for field, value in form.items()]
    parts.append(f'name="file"; filename={json.dumps(name)}\r\nContent-Type: text/plain\r\n\r\n')
    head = "".join(f"--{boundary}\r\nContent-Disposition: form-data; {part}" for part in parts).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    chunk = b"x" * CHUNK

    def body() -> Iterator[bytes]:
        yield head
        for offset in range(0, size, CHUNK):
            yield chunk[: size - offset]
        yield tail

    # requests sends a generator chunked.
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    return zac.post(url, data=body(), headers=headers, timeout=UPLOAD_TIMEOUT)


def uploaded_document(  # noqa: PLR0913  # the zaak, its taak and the form fields
    zac: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    *,
    suffix: str = "txt",
    taak: JsonObject | None = None,
    **fields: str,
) -> JsonObject:
    """Upload a document (suffix: a key of FILES) to the zaak, or its open taak, with these form fields."""
    extension = EXTENSIONS.get(suffix, suffix)
    response = upload(zac, zac_url, zaak, registry, extension=extension, file=FILES[suffix], taak=taak, **fields)
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


def zaak_documents(
    zac: requests.Session, zac_url: str, zaak: JsonObject, *, gekoppelde_zaken: bool = False
) -> list[JsonObject]:
    """Return the documents ZAC lists with the zaak; with gekoppelde_zaken also those of its related zaken."""
    body = {"zaakUUID": zaak["uuid"], "gekoppeldeZaakDocumenten": gekoppelde_zaken}
    listed = zac.put(f"{zac_url}/rest/informatieobjecten/informatieobjectenList", json=body)
    return entries(expect_status(listed, HTTPStatus.OK).json())


def document_historie(zac: requests.Session, zac_url: str, document: JsonObject) -> list[JsonObject]:
    """Return the document's historie lines as ZAC shows them, from Open Zaak's audittrail."""
    return get_entries(zac, f"{document_url(zac_url, document)}/historie")


def taak_documents(zac: requests.Session, zac_url: str, taak: JsonObject) -> list[JsonObject]:
    """Return the documents ZAC lists with the taak, as the taak's form reads its taakdocumenten."""
    query = {"zaakUUID": taak["zaakUuid"], "informatieobjectUUIDs": strings(taak.get("taakdocumenten"))}
    listed = zac.put(f"{zac_url}/rest/informatieobjecten/informatieobjectenList", json=query)
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


def inbox_document(zac: requests.Session, zac_url: str, document: JsonObject) -> JsonObject | None:
    """Return the entry of the Open Zaak document in ZAC's Inbox documenten, or None.

    Matched by uuid: the documents of one run share their titel.
    """
    found = inbox_documenten(zac, zac_url, str(document["titel"]))
    wanted = uuid_of(document["url"])
    return next((item for item in found if item.get("enkelvoudiginformatieobjectUUID") == wanted), None)


def delete_inbox_document(zac: requests.Session, zac_url: str, entry: JsonObject) -> requests.Response:
    """Delete an entry of ZAC's Inbox documenten and its document in Open Zaak; ZAC's answer."""
    return zac.delete(f"{zac_url}/rest/inboxdocumenten/{entry['id']}")


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
