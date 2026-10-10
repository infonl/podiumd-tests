"""Unit tests for PABC's entity type management."""

import pytest
import requests

from podiumd_tests.pabc import add_zaaktype_entity_type
from podiumd_tests.pabc import delete_entity_type
from podiumd_tests.pabc import zaaktype_entity_type
from podiumd_tests.responses import UnexpectedStatusError

PABC = "https://pabc.example.test"
ENTITY_TYPES = [
    {"id": "g-1", "entityTypeId": "1916", "type": "GEMEENTE", "name": "Leidschendam-Voorburg"},
    {"id": "z-1", "entityTypeId": "Test zaaktype 1", "type": "ZAAKTYPE", "name": "Test zaaktype 1"},
]


def test_finds_a_zaaktype_by_its_omschrijving(fake_http):
    fake_http({"/api/v1/entity-types": (200, ENTITY_TYPES)})
    assert zaaktype_entity_type(requests.Session(), PABC, "Test zaaktype 1") == "z-1"
    assert zaaktype_entity_type(requests.Session(), PABC, "1916") is None


def test_adds_and_deletes_an_entity_type(fake_http):
    sent = fake_http(
        {"POST /api/v1/entity-types": (201, {"id": "z-2"}), "DELETE /api/v1/entity-types/z-2": (204, None)}
    )
    assert add_zaaktype_entity_type(requests.Session(), PABC, "ptest-volume") == "z-2"
    delete_entity_type(requests.Session(), PABC, "z-2")
    assert b'"type": "ZAAKTYPE"' in sent[0].body
    assert [s.method for s in sent] == ["POST", "DELETE"]


def test_a_refused_add_raises(fake_http):
    fake_http({"POST /api/v1/entity-types": (409, {"title": "exists"})})
    with pytest.raises(UnexpectedStatusError):
        add_zaaktype_entity_type(requests.Session(), PABC, "ptest-volume")
