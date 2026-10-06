"""Unit tests for the OIDC login page checks."""

import pytest

from podiumd_tests.oidc import LoginPageError
from podiumd_tests.oidc import keycloak_login_realm

KEYCLOAK = "https://keycloak.example.test"
AUTH_URL = f"{KEYCLOAK}/realms/podiumd/protocol/openid-connect/auth?client_id=zac"
FORM = b'<form id="kc-form-login"><input id="username" name="username"></form>'


def test_login_form_gives_the_realm(response_factory):
    assert keycloak_login_realm(response_factory(body=FORM, url=AUTH_URL), KEYCLOAK) == "podiumd"


@pytest.mark.parametrize(
    ("status", "url", "body", "message"),
    [
        (502, AUTH_URL, FORM, "HTTP 502"),
        (200, "https://zac.example.test/", FORM, "not on Keycloak"),
        (200, f"{KEYCLOAK}/admin/master/console/", FORM, "not an OIDC auth endpoint"),
        (200, AUTH_URL, b"<p>We are sorry...</p>", "no login form"),
    ],
)
def test_anything_else_is_an_error(response_factory, status, url, body, message):
    with pytest.raises(LoginPageError, match=message):
        keycloak_login_realm(response_factory(status=status, body=body, url=url), KEYCLOAK)
