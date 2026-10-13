"""Unit tests for the OIDC login page checks."""

import pytest
import requests

from podiumd_tests.oidc import keycloak_hosts
from podiumd_tests.oidc import keycloak_login_realm
from podiumd_tests.oidc import logs_in_through_keycloak

KEYCLOAK = "https://keycloak.example.test"
HOSTS = {"keycloak.example.test", "keycloak-admin.example.test"}
AUTH_URL = f"{KEYCLOAK}/realms/podiumd/protocol/openid-connect/auth?client_id=zac"
FORM = b'<form id="kc-form-login"><input id="username" name="username"></form>'
OTHER_HOST_FORM = (
    b'<form id="kc-form-login" action="https://keycloak.example.test/realms/podiumd/login-actions/authenticate">'
    b'<input id="username" name="username"></form>'
)


def test_login_form_gives_the_realm(response_factory):
    assert keycloak_login_realm(response_factory(body=FORM, url=AUTH_URL), HOSTS) == "podiumd"


def test_login_form_on_the_admin_host_counts(response_factory):
    url = AUTH_URL.replace("keycloak.", "keycloak-admin.")
    assert keycloak_login_realm(response_factory(body=FORM, url=url), HOSTS) == "podiumd"


@pytest.mark.parametrize(
    ("status", "url", "body", "message"),
    [
        (502, AUTH_URL, FORM, "HTTP 502, expected 200"),
        (200, "https://zac.example.test/?error=invalid_scope", FORM, "not on Keycloak"),
        (200, f"{KEYCLOAK}/admin/master/console/", FORM, "not an OIDC auth endpoint"),
        (200, AUTH_URL, b"<p>We are sorry...</p>", "no login form"),
        (200, AUTH_URL.replace("keycloak.", "keycloak-admin."), OTHER_HOST_FORM, "posts to keycloak.example.test"),
    ],
)
def test_anything_else_is_an_error(response_factory, status, url, body, message):
    # LoginPageError, or UnexpectedStatusError for the status: both are AssertionErrors.
    with pytest.raises(AssertionError, match=message):
        keycloak_login_realm(response_factory(status=status, body=body, url=url), HOSTS)


def test_keycloak_hosts():
    urls = {"keycloak": KEYCLOAK, "keycloak-admin": "https://keycloak-admin.example.test", "zac": "https://zac.x"}
    assert keycloak_hosts(urls) == HOSTS
    assert keycloak_hosts({"keycloak": KEYCLOAK}) == {"keycloak.example.test"}


@pytest.mark.parametrize(
    ("status", "location", "expected"),
    [(302, AUTH_URL, True), (302, "https://openzaak.example.test/admin/login/", False), (200, None, False)],
)
def test_logs_in_through_keycloak(monkeypatch, response_factory, status, location, expected):
    response = response_factory(status=status)
    if location:
        response.headers["Location"] = location
    monkeypatch.setattr(requests.Session, "get", lambda *_a, **_k: response)
    assert (
        logs_in_through_keycloak(requests.Session(), "https://openzaak.example.test/oidc/authenticate/", HOSTS)
        is expected
    )


def test_logs_in_through_keycloak_fails_on_a_server_error(monkeypatch, response_factory):
    monkeypatch.setattr(requests.Session, "get", lambda *_a, **_k: response_factory(status=502))
    with pytest.raises(AssertionError, match="fails instead of answering its login"):
        logs_in_through_keycloak(requests.Session(), "https://openzaak.example.test/oidc/authenticate/", HOSTS)
