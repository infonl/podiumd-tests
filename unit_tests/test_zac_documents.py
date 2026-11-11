"""Unit tests for ZAC document uploads."""

import io
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
