"""Documents of a zaak in ZAC: test files, uploads through ZAC's REST API, and ZAC's list of them."""

from __future__ import annotations

import io
import zipfile

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

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
    "word": (DOCX, minimal_docx("podiumd-tests")),
    # About 300 pages: LibreOffice's memory grows with them; gotenberg stops a conversion after 30 s.
    "large-word": (DOCX, minimal_docx("podiumd-tests " * 20, paragraphs=10_000)),
}


def uploaded_document(  # noqa: PLR0913  # the upload form's choices
    zac: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    *,
    suffix: str = "txt",
    status: str = "definitief",
) -> JsonObject:
    """Upload a document (suffix: a key of FILES) to the zaak as the user does in ZAC; skips without a documenttype.

    The zaak's cleanup deletes it (delete_zaak with_documents).
    """
    documents = f"{zac_url}/rest/informatieobjecten"
    types = get_entries(zac, f"{documents}/informatieobjecttypes/zaak/{zaak['uuid']}")
    if not types:
        pytest.skip(f"zaaktype {section(zaak, 'zaaktype').get('identificatie')} has no informatieobjecttypen")
    formaat, content = FILES[suffix]
    name = f"{registry.tagged('document')}.{'docx' if suffix.endswith('word') else suffix}"
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
    upload = zac.post(
        f"{documents}/informatieobject/{zaak['uuid']}/{registry.tagged('upload')}",
        params={"taakObject": "false"},
        data=form,
        files={"file": (name, content, formaat)},
    )
    return expect_status(upload, HTTPStatus.OK).json()


def zaak_documents(zac: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the documents ZAC lists with the zaak."""
    listed = zac.put(f"{zac_url}/rest/informatieobjecten/informatieobjectenList", json={"zaakUUID": zaak["uuid"]})
    return entries(expect_status(listed, HTTPStatus.OK).json())
