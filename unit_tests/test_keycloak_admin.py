"""Unit tests for the Keycloak admin REST client."""

import json

import pytest
import requests

from podiumd_tests.auth.keycloak_admin import KeycloakAdmin

KC = "https://kc.test"
REALM = "/admin/realms/podiumd"
TOKEN = {"POST /realms/master/protocol/openid-connect/token": (200, {"access_token": "t"})}


@pytest.fixture
def admin(fake_http):
    """A KeycloakAdmin on fake_http; install(answers) returns it and the Sent requests."""

    def install(answers):
        sent = fake_http({**TOKEN, **{f"{m} {REALM}{p}": a for (m, p), a in answers.items()}})
        return KeycloakAdmin(requests.Session(), KC, "podiumd", ("admin", "pw")), sent

    return install


def calls(sent):
    return [f"{s.method} {s.url.split('?')[0].removeprefix(KC + REALM)}" for s in sent[1:]]


def test_create_user_clears_the_default_required_actions(admin):
    keycloak, sent = admin(
        {
            ("POST", "/users"): (201, None),
            ("GET", "/users"): (200, [{"id": "u1"}]),
            ("PUT", "/users/u1"): (204, None),
        }
    )
    assert keycloak.create_user("ptest-u", "pw", {}) == "u1"
    assert calls(sent) == ["POST /users", "GET /users", "PUT /users/u1"]
    assert json.loads(sent[1].body)["credentials"][0]["value"] == "pw"


def test_save_user_updates_an_existing_user_in_place(admin):
    keycloak, sent = admin(
        {
            ("GET", "/users"): (200, [{"id": "u1"}]),
            ("PUT", "/users/u1"): (204, None),
            ("PUT", "/users/u1/reset-password"): (204, None),
        }
    )
    assert keycloak.save_user("ptest-u", "pw", {}) == "u1"
    assert calls(sent) == ["GET /users", "PUT /users/u1", "PUT /users/u1/reset-password"]


def test_save_user_creates_a_missing_user(admin, monkeypatch):
    keycloak, _ = admin({("GET", "/users"): (200, [])})
    monkeypatch.setattr(keycloak, "create_user", lambda *_args: "new")
    assert keycloak.save_user("ptest-u", "pw", {}) == "new"


def test_create_user_that_does_not_appear_is_an_error(admin):
    keycloak, _ = admin({("POST", "/users"): (201, None), ("GET", "/users"): (200, [])})
    with pytest.raises(LookupError, match="user ptest-u not found after creating it"):
        keycloak.create_user("ptest-u", "pw", {})


def test_users_asks_for_all_matches(admin):
    keycloak, sent = admin({("GET", "/users/count"): (200, 2), ("GET", "/users"): (200, [{"id": "a"}, {"id": "b"}])})
    assert [u["id"] for u in keycloak.users("ptest-")] == ["a", "b"]
    assert "max=2" in sent[-1].url


@pytest.mark.parametrize(
    ("status", "body", "refusal"),
    [(204, None, None), (400, {"error": "invalidPasswordMinLengthMessage"}, "invalidPasswordMinLengthMessage")],
)
def test_password_refusal(admin, status, body, refusal):
    keycloak, _ = admin({("PUT", "/users/u1/reset-password"): (status, body)})
    assert keycloak.password_refusal("u1", "pw") == refusal


def test_client_role_of_a_missing_client_is_none(admin):
    keycloak, _ = admin({("GET", "/clients"): (200, [])})
    assert keycloak.client_role("zac", "behandelaar") is None


def test_create_client_scope_returns_its_id(admin):
    keycloak, sent = admin(
        {("POST", "/client-scopes"): (201, None), ("GET", "/client-scopes"): (200, [{"name": "s", "id": "s1"}])}
    )
    assert keycloak.create_client_scope({"name": "s"}) == "s1"
    assert calls(sent) == ["POST /client-scopes", "GET /client-scopes"]


def test_single_calls_use_their_admin_paths(admin):
    keycloak, sent = admin(
        {
            ("GET", "/attack-detection/brute-force/users/u1"): (200, {"disabled": False}),
            ("GET", "/clients/c1/client-secret"): (200, {"value": "s3cret"}),
            ("DELETE", "/users/u1"): (204, None),
            ("PUT", "/users/u1/groups/g1"): (204, None),
            ("DELETE", "/client-scopes/s1"): (204, None),
        }
    )
    assert keycloak.brute_force_status("u1") == {"disabled": False}
    assert keycloak.client_secret("c1") == "s3cret"
    keycloak.delete_user("u1")
    keycloak.join_group("u1", "g1")
    keycloak.delete_client_scope("s1")
    assert calls(sent)[2:] == ["DELETE /users/u1", "PUT /users/u1/groups/g1", "DELETE /client-scopes/s1"]
    assert sent[-1].headers["Authorization"] == "Bearer t"


def test_server_info_is_outside_the_realm(fake_http):
    sent = fake_http({**TOKEN, "GET /admin/serverinfo": (200, {"systemInfo": {}})})
    assert KeycloakAdmin(requests.Session(), KC, "master", ("admin", "pw")).server_info() == {"systemInfo": {}}
    assert sent[-1].url == f"{KC}/admin/serverinfo"
