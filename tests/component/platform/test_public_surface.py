"""What anonymous and malformed requests get: no admin pages, no server errors.

Ported from TA regression 120 (Open Formulieren payments), 121 (graceful degradation) and
177 (admin endpoints not public). TA allowed "anything below 500" in many places; where the
right answer is known, it is asserted.
"""

from __future__ import annotations

import re

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak import admin_realm_url
from podiumd_tests.auth.keycloak_admin import realm_of
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import is_server_error
from podiumd_tests.seed.openzaak import ZAKEN

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

pytestmark = pytest.mark.component

NIL = "00000000-0000-0000-0000-000000000000"
LOGIN = re.compile(r"login|auth|signin|oidc", re.IGNORECASE)
DJANGO_APPS = (
    "openzaak",
    "openklant",
    "openformulieren",
    "openinwoner",
    "openarchiefbeheer",
    "objecten",
    "objecttypen",
    "opennotificaties",
)


@pytest.mark.parametrize("component", [requiring(c, c) for c in DJANGO_APPS])
def test_django_admin_is_not_public(http: requests.Session, urls: dict[str, str], component: str) -> None:
    """Anonymous /admin/ ends on a login page, never on the admin itself (TA reg-177)."""
    response = http.get(urls[component] + "/admin/", allow_redirects=False)
    if response.is_redirect:
        assert LOGIN.search(response.headers["Location"]), response.headers["Location"]
        return
    assert response.status_code in REFUSED, describe(response)


@pytest.mark.requires("keycloak")
def test_keycloak_admin_api_is_not_public(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment
) -> None:
    """The Keycloak admin API refuses an anonymous request (TA reg-177)."""
    realm = realm_of(podiumd_env)
    response = http.get(admin_realm_url(urls.get("keycloak-admin") or urls["keycloak"], realm))
    assert response.status_code in REFUSED, describe(response)


@pytest.mark.requires("openzaak")
def test_openzaak_refuses_a_bogus_token(http: requests.Session, urls: dict[str, str]) -> None:
    """A token that is not a JWT gets 401 or 403 (TA reg-121)."""
    response = http.get(f"{urls['openzaak']}/{ZAKEN}/zaken", headers={"Authorization": "Bearer ptest-bogus"})
    assert response.status_code in REFUSED, describe(response)


@pytest.mark.requires("openzaak")
def test_openzaak_unknown_zaak_and_bad_ordering(openzaak: ApiClient) -> None:
    """An unknown zaak is a 404 and an unknown ordering field a 400, not a server error (TA reg-121)."""
    openzaak.request("GET", f"{ZAKEN}/zaken/{NIL}", HTTPStatus.NOT_FOUND)
    response = openzaak.http.get(
        openzaak.url(f"{ZAKEN}/zaken"), params={"ordering": "ptest-onbekend"}, headers=openzaak.headers()
    )
    assert not is_server_error(response), describe(response)


@pytest.mark.requires("openklant")
def test_openklant_unknown_partij(openklant: ApiClient) -> None:
    """An unknown partij is a 404 (TA reg-121)."""
    openklant.request("GET", f"partijen/{NIL}", HTTPStatus.NOT_FOUND)


@pytest.mark.requires("openformulieren")
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"/api/v2/forms/{NIL}"),
        ("GET", f"/api/v2/submissions/{NIL}"),
        ("GET", "/api/v2/payment-plugins"),
        ("GET", f"/payments/{NIL}/return"),
        ("GET", f"/payments/{NIL}/link"),
        ("POST", "/payments/ogone/webhook"),
        ("POST", "/payments/worldline/webhook"),
    ],
)
def test_openformulieren_without_session(http: requests.Session, urls: dict[str, str], method: str, path: str) -> None:
    """Unknown forms, submissions and payments, and empty payment webhooks, give no server error (TA reg-120, 121)."""
    response = http.request(method, urls["openformulieren"] + path, json={} if method == "POST" else None)
    assert not is_server_error(response), describe(response)
