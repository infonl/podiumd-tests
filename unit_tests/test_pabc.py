"""Unit tests for PABC's decision endpoint, login and entity type management."""

import json

from contextlib import nullcontext

import pytest
import requests

from podiumd_tests import pabc
from podiumd_tests.pabc import add_entity_type
from podiumd_tests.pabc import decide
from podiumd_tests.pabc import delete_entity_type
from podiumd_tests.pabc import find_entity_type
from podiumd_tests.responses import UnexpectedStatusError

PABC = "https://pabc.example.test"
ENTITY_TYPES = [
    {"id": "g-1", "entityTypeId": "1916", "type": "GEMEENTE", "name": "Leidschendam-Voorburg"},
    {"id": "z-1", "entityTypeId": "Test zaaktype 1", "type": "ZAAKTYPE", "name": "Test zaaktype 1"},
]


def test_finds_a_zaaktype_by_its_omschrijving(fake_http):
    fake_http({"/api/v1/entity-types": (200, ENTITY_TYPES)})
    assert find_entity_type(requests.Session(), PABC, "Test zaaktype 1") == "z-1"
    assert find_entity_type(requests.Session(), PABC, "1916") is None
    assert find_entity_type(requests.Session(), PABC, "Test zaaktype 1", "GEMEENTE") is None


def test_adds_and_deletes_an_entity_type(fake_http):
    sent = fake_http(
        {"POST /api/v1/entity-types": (201, {"id": "z-2"}), "DELETE /api/v1/entity-types/z-2": (204, None)}
    )
    assert add_entity_type(requests.Session(), PABC, "ptest-volume") == "z-2"
    delete_entity_type(requests.Session(), PABC, "z-2")
    assert b'"type": "ZAAKTYPE"' in sent[0].body
    assert [s.method for s in sent] == ["POST", "DELETE"]


def test_adds_a_gemeente_by_its_code_and_name(fake_http):
    sent = fake_http({"POST /api/v1/entity-types": (201, {"id": "g-1"})})
    assert add_entity_type(requests.Session(), PABC, "0530", "GEMEENTE", "Hellevoetsluis") == "g-1"
    assert json.loads(sent[0].body) == {"entityTypeId": "0530", "type": "GEMEENTE", "name": "Hellevoetsluis"}


def test_a_refused_add_raises(fake_http):
    fake_http({"POST /api/v1/entity-types": (409, {"title": "exists"})})
    with pytest.raises(UnexpectedStatusError):
        add_entity_type(requests.Session(), PABC, "ptest-volume")


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


def test_ensure_domain_creates_it_and_adds_only_missing_entity_types(fake_http):
    sent = fake_http(
        {
            "GET /api/v1/domains": (200, [{"id": "d-1", "name": "ptest", "entityTypes": ["e-1"]}]),
            "POST /api/v1/domains/d-1/entity-types/e-2": (204, None),
        }
    )
    assert pabc.ensure_domain(requests.Session(), PABC, "ptest", ["e-1", "e-2"]) == "d-1"
    assert [f"{s.method} {s.url.removeprefix(PABC)}" for s in sent if s.method == "POST"] == [
        "POST /api/v1/domains/d-1/entity-types/e-2"
    ]


def test_ensure_functional_role_maps_only_the_missing_application_roles(fake_http):
    roles = [
        {"id": "a-1", "name": "behandelaar", "application": "zaakafhandelcomponent"},
        {"id": "a-2", "name": "coordinator", "application": "zaakafhandelcomponent"},
        {"id": "a-3", "name": "behandelaar", "application": "other"},
    ]
    mapped = [{"applicationRoleId": "a-1", "domain": "ptest"}]
    sent = fake_http(
        {
            "GET /api/v1/functional-roles": (200, [{"id": "f-1", "name": "ptest-zac", "mappings": mapped}]),
            "GET /api/v1/application-roles": (200, roles),
            "POST /api/v1/functional-roles/f-1/mappings": (201, {}),
        }
    )
    pabc.ensure_functional_role(
        requests.Session(), PABC, "ptest-zac", "zaakafhandelcomponent", ("behandelaar", "coordinator"), "d-1"
    )
    posted = [json.loads(s.body) for s in sent if s.method == "POST"]
    assert posted == [{"applicationRoleId": "a-2", "domainId": "d-1", "isAllEntityTypes": False}]
    assert pabc.domain_mappings(requests.Session(), PABC, "ptest-zac") == 1


def test_ensure_functional_role_refuses_an_application_role_pabc_lacks(fake_http):
    fake_http(
        {
            "GET /api/v1/functional-roles": (200, [{"id": "f-1", "name": "ptest-zac", "mappings": []}]),
            "GET /api/v1/application-roles": (200, [{"id": "a-1", "name": "behandelaar", "application": "zac"}]),
        }
    )
    with pytest.raises(LookupError, match="no application role brp_zoeken of zac"):
        pabc.ensure_functional_role(requests.Session(), PABC, "ptest-zac", "zac", ("behandelaar", "brp_zoeken"), "d")


def test_delete_functional_roles_and_domain_deletes_each_named_one(fake_http):
    sent = fake_http(
        {
            "GET /api/v1/functional-roles": (
                200,
                [{"id": "f-1", "name": "a"}, {"id": "f-2", "name": "b"}, {"id": "f-3", "name": "c"}],
            ),
            "GET /api/v1/domains": (200, [{"id": "d-1", "name": "ptest"}]),
            "DELETE /api/v1/functional-roles/f-1": (204, None),
            "DELETE /api/v1/functional-roles/f-2": (204, None),
            "DELETE /api/v1/domains/d-1": (204, None),
        }
    )
    pabc.delete_roles_and_domain(requests.Session(), PABC, ("a", "b"), "ptest")
    assert [s.url.removeprefix(PABC) for s in sent if s.method == "DELETE"] == [
        "/api/v1/functional-roles/f-1",
        "/api/v1/functional-roles/f-2",
        "/api/v1/domains/d-1",
    ]


def test_mapped_application_roles_of_one_entity_type():
    decision = {
        "results": [
            {"entityType": {"id": "zt-1"}, "applicationRoles": [{"name": "behandelaar"}, {"name": "coordinator"}]},
            {"applicationRoles": [{"name": "brp_zoeken"}]},
        ]
    }
    assert pabc.mapped_application_roles(decision, "zt-1") == {"behandelaar", "coordinator"}
    assert pabc.mapped_application_roles(decision, "zt-2") == set()
