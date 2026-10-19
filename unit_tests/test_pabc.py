"""Unit tests for PABC's decision endpoint, login and entity type management."""

from contextlib import nullcontext

import pytest
import requests

from podiumd_tests import pabc
from podiumd_tests.pabc import add_zaaktype_entity_type
from podiumd_tests.pabc import decide
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


def test_decide_sends_the_api_key_and_the_role_names(fake_http):
    sent = fake_http({"POST /api/v1/application-roles-per-entity-type": (200, [])})
    decide(requests.Session(), PABC, "key-1", ["Behandelaar"])
    assert sent[0].headers["X-API-KEY"] == "key-1"
    assert sent[0].body == b'{"FunctionalRoleNames": ["Behandelaar"]}'


@pytest.mark.parametrize("logged_in", [True, False])
def test_login_checks_that_pabc_kept_the_session(monkeypatch, fake_http, page_env, logged_in):
    fake_http({"/api/me": (200, {"isLoggedIn": logged_in})})
    monkeypatch.setattr(pabc, "challenge_login", lambda *_a: requests.Session())
    if logged_in:
        assert isinstance(pabc.login(None, page_env(), "beheerder", "pw"), requests.Session)  # pyright: ignore[reportArgumentType]
    else:
        with pytest.raises(AssertionError, match="kept no session"):
            pabc.login(None, page_env(), "beheerder", "pw")  # pyright: ignore[reportArgumentType]


def test_admin_session_logs_in_on_a_headless_page(monkeypatch, page_env):
    monkeypatch.setattr(pabc, "headless_page", lambda _env: nullcontext("page"))
    monkeypatch.setattr(pabc, "login", lambda page, _env, user, _pw: (page, user))
    assert pabc.admin_session(page_env(), "beheerder", "pw") == ("page", "beheerder")
