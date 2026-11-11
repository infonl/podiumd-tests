"""Unit tests for ZAC document uploads."""

import io
import json
import zipfile

import pytest
import requests

from podiumd_tests import zac_documents
from podiumd_tests.seed.registry import ResourceRegistry

ZAC = "https://zac.example.test"


def test_minimal_docx_holds_the_text_in_each_paragraph():
    with zipfile.ZipFile(io.BytesIO(zac_documents.minimal_docx("hallo", paragraphs=2))) as docx:
        assert docx.read("word/document.xml").decode().count("<w:t>hallo</w:t>") == 2


def test_uploaded_document_uses_the_first_documenttype(fake_http):
    sent = fake_http(
        {
            "GET /rest/informatieobjecten/informatieobjecttypes/zaak/z1": (200, [{"uuid": "iot1"}]),
            "POST /rest/informatieobjecten/informatieobject/z1/ptest-x-upload": (200, {"uuid": "d1"}),
        }
    )
    document = zac_documents.uploaded_document(requests.Session(), ZAC, {"uuid": "z1"}, ResourceRegistry("ptest-x"))
    assert document == {"uuid": "d1"}
    assert b'name="informatieobjectTypeUUID"\r\n\r\niot1' in sent[-1].body


def test_uploaded_document_skips_without_a_documenttype(fake_http):
    fake_http({"GET /rest/informatieobjecten/informatieobjecttypes/zaak/z1": (200, [])})
    with pytest.raises(pytest.skip.Exception, match="no informatieobjecttypen"):
        zac_documents.uploaded_document(
            requests.Session(), ZAC, {"uuid": "z1", "zaaktype": {}}, ResourceRegistry("ptest-x")
        )


def test_zaak_documents_lists_zacs_answer(fake_http):
    fake_http({"PUT /rest/informatieobjecten/informatieobjectenList": (200, [{"uuid": "d1"}])})
    assert zac_documents.zaak_documents(requests.Session(), ZAC, {"uuid": "z1"}) == [{"uuid": "d1"}]


UPLOAD = {
    "GET /rest/informatieobjecten/informatieobjecttypes/zaak/z1": (200, [{"uuid": "iot1"}]),
    "POST /rest/informatieobjecten/informatieobject/z1/ptest-x-upload": (400, {}),
}


def test_upload_returns_zacs_answer_and_sends_an_eml_as_octet_stream(fake_http):
    sent = fake_http(UPLOAD)
    registry = ResourceRegistry("ptest-x")
    response = zac_documents.upload(
        requests.Session(), ZAC, {"uuid": "z1"}, registry, extension="eml", file=zac_documents.FILES["eml"]
    )
    assert response.status_code == 400
    body = sent[-1].body
    assert b'filename="ptest-x-document.eml"\r\nContent-Type: application/octet-stream' in body
    assert b'name="formaat"\r\n\r\nmessage/rfc822' in body


def test_nieuwe_versie_starts_from_the_current_version(fake_http):
    current = {"uuid": "d1", "bestandsnaam": "v1.txt", "titel": "v1", "taal": {"code": "dut"}, "status": "definitief"}
    sent = fake_http(
        {
            "GET /rest/informatieobjecten/informatieobject/d1/huidigeversie": (200, current),
            "PUT /rest/informatieobjecten/informatieobject/d1": (200, {"versie": 2}),
        }
    )
    response = zac_documents.nieuwe_versie(
        requests.Session(), ZAC, {"uuid": "z1"}, {"uuid": "d1"}, {"titel": "v2"}, ("v2.txt", "text/plain", b"2")
    )
    assert response.json() == {"versie": 2}
    body = sent[-1].body
    assert sent[-1].url.endswith("/d1?zaak=z1")
    assert b'name="titel"\r\n\r\nv2\r\n' in body
    assert b'name="taal"\r\n\r\n{"code": "dut"}\r\n' in body
    assert b'name="bestandsnaam"\r\n\r\nv2.txt\r\n' in body
    assert b'name="uuid"' not in body


def test_nieuwe_versie_without_a_file_sends_no_file(fake_http):
    sent = fake_http(
        {
            "GET /rest/informatieobjecten/informatieobject/d1/huidigeversie": (200, {"bestandsnaam": "v1.txt"}),
            "PUT /rest/informatieobjecten/informatieobject/d1": (200, {}),
        }
    )
    zac_documents.nieuwe_versie(requests.Session(), ZAC, {"uuid": "z1"}, {"uuid": "d1"}, {"beschrijving": "b"})
    assert b'name="file"' not in sent[-1].body
    assert b'name="bestandsnaam"' not in sent[-1].body


def test_taal_finds_the_code(fake_http):
    talen = [{"code": "dut", "naam": "Nederlands"}, {"code": "eng", "naam": "Engels"}]
    fake_http({"GET /rest/configuratie/talen": (200, talen)})
    assert zac_documents.taal(requests.Session(), ZAC, "eng") == talen[1]


def test_verplaats_document_names_the_bron_and_the_target_zaak(fake_http):
    sent = fake_http({"POST /rest/informatieobjecten/informatieobject/verplaats": (204, None)})
    zac_documents.verplaats_document(
        requests.Session(), ZAC, {"uuid": "d1"}, zac_documents.ONTKOPPELDE_DOCUMENTEN, {"identificatie": "ZAAK-2"}
    )
    assert json.loads(sent[-1].body) == {
        "documentUUID": "d1",
        "bron": "ontkoppelde-documenten",
        "nieuweZaakID": "ZAAK-2",
    }


def test_ontkoppel_document_cleanup_deletes_only_its_detached_entry(fake_http):
    detached = {"resultaten": [{"id": 7, "documentUUID": "d1"}, {"id": 8, "documentUUID": "d2"}]}
    sent = fake_http(
        {
            "PUT /rest/zaken/zaakinformatieobjecten/ontkoppel": (204, None),
            "PUT /rest/ontkoppeldedocumenten": (200, detached),
            "DELETE /rest/ontkoppeldedocumenten/7": (204, None),
        }
    )
    registry = ResourceRegistry("ptest-x")
    zaak = {"uuid": "z1", "identificatie": "ZAAK-1"}
    zac_documents.ontkoppel_document(requests.Session(), ZAC, zaak, {"uuid": "d1"}, "reden", registry)
    assert json.loads(sent[-1].body) == {"zaakUUID": "z1", "documentUUID": "d1", "reden": "reden"}
    registry.cleanup()
    assert json.loads(sent[-2].body)["zaakID"] == "ZAAK-1"
    assert [(request.method, request.url) for request in sent[-1:]] == [
        ("DELETE", f"{ZAC}/rest/ontkoppeldedocumenten/7")
    ]
