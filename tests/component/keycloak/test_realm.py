"""Keycloak realm of the environment: discovery, signing keys and grant types. Ported from TA regression 91."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak import discovery_url
from podiumd_tests.auth.keycloak import realm_url
from podiumd_tests.json_data import entries
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("keycloak")]


@pytest.fixture(name="realm")
def fixture_realm(podiumd_env: Environment) -> str:
    """The realm the applications log in to (settings.keycloak_realm, default podiumd)."""
    return podiumd_env.profile.settings.get("keycloak_realm", "podiumd")


def test_discovery_document(http: requests.Session, urls: dict[str, str], realm: str) -> None:
    """The realm publishes its endpoints on the Keycloak host, and supports the code and password grants."""
    config = http.get(discovery_url(urls["keycloak"], realm)).json()
    for key in ("issuer", "token_endpoint", "authorization_endpoint", "jwks_uri"):
        assert config[key], key
    assert url_host(str(config["issuer"])) == url_host(urls["keycloak"])
    assert {"authorization_code", "password"} <= set(config["grant_types_supported"])


def test_signing_keys(http: requests.Session, urls: dict[str, str], realm: str) -> None:
    """The realm has a public key and at least one signing key in its JWKS."""
    config = http.get(discovery_url(urls["keycloak"], realm)).json()
    keys = entries(http.get(str(config["jwks_uri"])).json()["keys"])
    assert keys
    assert all(k.get("kty") for k in keys)
    realm_info = http.get(realm_url(urls["keycloak"], realm)).json()
    assert (realm_info["realm"], bool(realm_info["public_key"])) == (realm, True)
