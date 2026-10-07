"""PKCE on the OIDC logins. Ported from podiumd-minikube and podiumd-infra test_pkce.py.

PABC always sends a PKCE code challenge (UsePkce is hard-coded in its source); the Django apps'
clients must not require PKCE, which mozilla-django-oidc does not send. MK's login round trip
and ZAC's experimental PKCE are not ported (MK-specific).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.json_data import section
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    import requests

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("keycloak")]

DJANGO_CLIENTS = (
    "openzaak",
    "openklant",
    "objecten",
    "objecttypen",
    "opennotificaties",
    "openformulieren",
    "openarchiefbeheer",
)


@pytest.fixture(scope="module", name="keycloak_admin")
def fixture_keycloak_admin(podiumd_env: Environment) -> KeycloakAdmin:
    """Admin API of the environment's realm."""
    return for_environment(podiumd_env)


@pytest.mark.requires("pabc")
def test_pabc_challenge_sends_a_pkce_code_challenge(http: requests.Session, urls: dict[str, str]) -> None:
    """PABC's login challenge points at Keycloak with client pabc and an S256 code challenge."""
    response = http.get(urls["pabc"] + "/api/challenge", params={"returnUrl": "/"}, allow_redirects=False)
    location = response.headers["Location"]  # 401 for a non-browser request, 302 for a browser
    assert url_host(location) == url_host(urls["keycloak"])
    query = parse_qs(urlsplit(location).query)
    assert query["client_id"] == ["pabc"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]


@pytest.mark.parametrize("client_id", DJANGO_CLIENTS)
def test_django_app_client_does_not_require_pkce(keycloak_admin: KeycloakAdmin, client_id: str) -> None:
    """A Django app's Keycloak client leaves pkce.code.challenge.method empty."""
    client = keycloak_admin.client(client_id)
    if client is None:
        pytest.skip(f"no Keycloak client {client_id} in this realm")
    assert section(client, "attributes").get("pkce.code.challenge.method", "") == ""
