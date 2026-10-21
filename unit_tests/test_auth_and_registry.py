"""Unit tests for ZGW tokens, Keycloak logins and the cleanup registry."""

import base64
import hashlib
import hmac
import json

import pytest
import requests

from podiumd_tests.auth.keycloak import PasswordLogin
from podiumd_tests.auth.keycloak import TokenError
from podiumd_tests.auth.keycloak import discovery_url
from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.auth.keycloak import password_grant
from podiumd_tests.auth.keycloak import realm_url
from podiumd_tests.auth.keycloak import totp
from podiumd_tests.auth.zgw_jwt import unsigned_jwt
from podiumd_tests.auth.zgw_jwt import zgw_headers
from podiumd_tests.auth.zgw_jwt import zgw_jwt
from podiumd_tests.seed.registry import CleanupError
from podiumd_tests.seed.registry import ResourceRegistry


def b64decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_totp_matches_the_rfc_6238_vectors():
    key = "GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ"  # base32 of "12345678901234567890"
    assert totp(key, at=59) == "287082"
    assert totp(key.lower(), at=1111111109) == "081804"


def test_zgw_jwt_is_a_valid_hs256_token():
    token = zgw_jwt("zac", "secret", issued_at=1700000000)
    header, payload, signature = token.split(".")
    expected = hmac.new(b"secret", f"{header}.{payload}".encode(), hashlib.sha256).digest()
    assert b64decode(signature) == expected
    assert json.loads(b64decode(header))["alg"] == "HS256"
    assert json.loads(b64decode(payload)) == {
        "iss": "zac",
        "iat": 1700000000,
        "client_id": "zac",
        "user_id": "zac",
        "user_representation": "zac",
    }


def test_unsigned_jwt_has_alg_none_and_no_signature():
    header, payload, signature = unsigned_jwt({"name": "x"}).split(".")
    assert json.loads(b64decode(header))["alg"] == "none"
    assert json.loads(b64decode(payload)) == {"name": "x"}
    assert signature == ""


def test_zgw_jwt_user_becomes_the_user_representation():
    payload = zgw_jwt("zac", "secret", user="podiumd-tests ptest-abc123").split(".")[1]
    assert json.loads(b64decode(payload))["user_representation"] == "podiumd-tests ptest-abc123"


def test_registry_deletes_in_reverse_order():
    deleted = []
    registry = ResourceRegistry("ptest-abc123")
    registry.add("zaaktype", lambda: deleted.append("zaaktype"))
    registry.add("zaak", lambda: deleted.append("zaak"))
    assert registry.cleanup() == []
    assert deleted == ["zaak", "zaaktype"]
    assert len(registry) == 0


def test_registry_runs_every_deleter_and_reports_failures():
    deleted = []

    def boom():
        msg = "404"
        raise RuntimeError(msg)

    registry = ResourceRegistry("ptest-abc123")
    registry.add("first", lambda: deleted.append("first"))
    registry.add("broken", boom)
    with pytest.raises(CleanupError, match="broken: RuntimeError: 404"):
        registry.cleanup()
    assert deleted == ["first"]


def test_keep_data_skips_cleanup():
    registry = ResourceRegistry("ptest-abc123", keep=True)
    registry.add("zaak ZAAK-1", lambda: pytest.fail("must not delete"))
    assert registry.cleanup() == ["zaak ZAAK-1"]
    assert registry.tagged("catalogus") == "ptest-abc123-catalogus"


def test_zgw_headers_carry_the_token_and_crs():
    headers = zgw_headers("tok")
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Accept-Crs"] == headers["Content-Crs"] == "EPSG:4326"


def test_realm_urls():
    assert realm_url("https://kc.test", "podiumd", "/protocol/openid-connect/token") == (
        "https://kc.test/realms/podiumd/protocol/openid-connect/token"
    )
    assert (
        discovery_url("https://kc.test", "master") == "https://kc.test/realms/master/.well-known/openid-configuration"
    )


KC = "https://kc.test"


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, {"error": "invalid_grant"}, "token request for 'u' in realm 'podiumd' failed"),
        (200, {}, "no access_token"),
    ],
)
def test_password_grant_failures_name_the_user(fake_http, status, body, error):
    fake_http({"POST /realms/podiumd/protocol/openid-connect/token": (status, body)})
    with pytest.raises(TokenError, match=error):
        password_grant(requests.Session(), KC, "podiumd", PasswordLogin("c", "u", "p"))


def test_password_grant_sends_the_client_secret(fake_http):
    sent = fake_http({"POST /realms/podiumd/protocol/openid-connect/token": (200, {"access_token": "t"})})
    assert password_grant(requests.Session(), KC, "podiumd", PasswordLogin("c", "u", "p", "s3cret")) == "t"
    assert "client_secret=s3cret" in str(sent[0].body)


LOGIN_PAGE = '<form id="kc-form-login" action="https://kc.test/login?a=1&amp;b=2" method="post">'


class FakeBrowser:
    """A session that answers GET and each POST with the next page."""

    def __init__(self, response_factory, *pages):
        self.pages = [response_factory(body=page.encode(), url=f"{KC}/page{i}") for i, page in enumerate(pages)]
        self.posts = []

    def get(self, _url):
        return self.pages.pop(0)

    def post(self, url, data):
        self.posts.append((url, data))
        return self.pages.pop(0)


def test_form_login_posts_the_credentials_and_follows_a_form_post(response_factory):
    form_post = '<FORM METHOD="POST" ACTION="https://app.test/cb"><INPUT NAME="code" VALUE="a&amp;b"/></FORM>'
    http = FakeBrowser(response_factory, LOGIN_PAGE, form_post, "app")
    assert form_login(http, "https://app.test/login", "u", "p").text == "app"  # pyright: ignore[reportArgumentType]
    assert http.posts == [
        ("https://kc.test/login?a=1&b=2", {"username": "u", "password": "p"}),
        ("https://app.test/cb", {"code": "a&b"}),
    ]


@pytest.mark.parametrize(
    ("pages", "error"),
    [
        (("no form",), "no Keycloak login form at https://kc.test/page0"),
        ((LOGIN_PAGE, LOGIN_PAGE), "refused the login of 'u'"),
    ],
)
def test_form_login_failures(response_factory, pages, error):
    with pytest.raises(TokenError, match=error):
        form_login(FakeBrowser(response_factory, *pages), "https://app.test/login", "u", "p")  # pyright: ignore[reportArgumentType]
