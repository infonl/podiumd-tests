"""Keycloak realms of the environment: discovery, signing keys, grant types (TA regression 91) and security policy."""

from __future__ import annotations

import secrets

from typing import TYPE_CHECKING
from urllib.parse import urlencode

import pytest

from podiumd_tests.auth.keycloak import TokenError
from podiumd_tests.auth.keycloak import discovery_url
from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.auth.keycloak import realm_url
from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.auth.keycloak_admin import realm_of
from podiumd_tests.json_data import entries
from podiumd_tests.responses import url_host
from podiumd_tests.security import realm_policy_gaps

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("keycloak")]


@pytest.fixture(name="realm")
def fixture_realm(podiumd_env: Environment) -> str:
    """The realm the applications log in to (settings.keycloak_realm, default podiumd)."""
    return realm_of(podiumd_env)


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


@pytest.mark.parametrize("which", ["login", "master"])
def test_realm_meets_the_security_policy(podiumd_env: Environment, which: str) -> None:
    """The realm locks out password guessing, keeps tokens short and logs events, as podiumd's realm templates do."""
    realm = realm_of(podiumd_env) if which == "login" else "master"
    gaps = realm_policy_gaps(for_environment(podiumd_env, realm).representation())
    assert not gaps, f"realm {realm}: {'; '.join(gaps)}"


def test_password_guessing_locks_the_user_out(
    podiumd_env: Environment, urls: dict[str, str], realm: str, registry: ResourceRegistry
) -> None:
    """After failureFactor wrong passwords Keycloak locks the user, and then refuses the right one too."""
    admin = for_environment(podiumd_env, realm)
    username, password = registry.tagged("lockout"), secrets.token_hex(20)
    user_id = admin.create_user(username, password, {})
    registry.add(f"keycloak user {username}", lambda: admin.delete_user(user_id))
    # Keycloak's own account client: its auth URL shows the login form without an app in between.
    query = {
        "client_id": "account",
        "response_type": "code",
        "redirect_uri": realm_url(urls["keycloak"], realm, "/account/"),
    }
    login = realm_url(urls["keycloak"], realm, "/protocol/openid-connect/auth?" + urlencode(query))
    for _ in range(int(str(admin.representation()["failureFactor"]))):
        with pytest.raises(TokenError):
            form_login(podiumd_env.session(), login, username, "ptest-wrong-password")
    assert admin.brute_force_status(user_id)["disabled"] is True
    with pytest.raises(TokenError):
        form_login(podiumd_env.session(), login, username, password)
