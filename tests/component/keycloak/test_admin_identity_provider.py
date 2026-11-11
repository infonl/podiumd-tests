"""An admin identity provider that grants a Keycloak admin role must allow admin role mapping.

Keycloak 26.8 (CVE-2026-12388) refuses an oidc-hardcoded-role-idp-mapper that grants an admin role unless the
identity provider has config.allowAdminRoleMapping "true"; the master realm import then fails (podiumd-chart-17,
helm-charts #623). The import succeeds here, so the config must be consistent. Environments without an admin
identity provider skip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.browser import configure_totp
from podiumd_tests.browser import keycloak_login

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("keycloak-admin")]

# Hardcoded-role mapper types, and the master realm role names that are admin by name.
ROLE_MAPPER = "oidc-hardcoded-role-idp-mapper"
ADMIN_ROLES = frozenset(("admin",))


def _is_admin_grant(mapper: JsonObject) -> bool:
    config = mapper.get("config") or {}
    role = str(config.get("role", "")) if isinstance(config, dict) else ""
    return mapper.get("identityProviderMapper") == ROLE_MAPPER and role.rsplit(".", maxsplit=1)[-1] in ADMIN_ROLES


def _admin_role_providers(admin: KeycloakAdmin) -> list[JsonObject]:
    """The master realm's identity providers with a mapper that grants the admin role; skips when none."""
    providers = [
        p
        for p in admin.identity_providers()
        if any(_is_admin_grant(m) for m in admin.identity_provider_mappers(str(p["alias"])))
    ]
    if not providers:
        pytest.skip("no identity provider in the master realm grants a Keycloak admin role")
    return providers


@pytest.mark.source(
    "podiumd-tests",
    "Keycloak 26.8 refuses an admin-role IdP mapper unless the IdP allows admin role mapping; the realm import fails.",
)
@pytest.mark.scenario("""
    Given an identity provider of the Keycloak realm master that grants the admin role
    When its configuration is read
    Then it allows admin role mapping
""")
def test_admin_role_identity_provider_allows_admin_role_mapping(podiumd_env: Environment) -> None:
    """Every master-realm IdP whose mapper grants the admin role has config.allowAdminRoleMapping true."""
    offenders = []
    for provider in _admin_role_providers(for_environment(podiumd_env, "master")):
        config = provider.get("config") or {}
        allow = str(config.get("allowAdminRoleMapping", "")) if isinstance(config, dict) else ""
        if allow != "true":
            offenders.append(f"{provider['alias']}: allowAdminRoleMapping={allow or 'unset'}")
    assert not offenders, f"admin-role identity providers without allowAdminRoleMapping: {offenders}"


@pytest.mark.source(
    "podiumd-tests",
    "An admin console login through the admin-role identity provider, with TOTP enrolment, gives the user admin.",
)
@pytest.mark.scenario("""
    Given the test user of the admin identity provider has never logged in to Keycloak
    When the user logs in to the Keycloak admin console through that identity provider
    And the user sets up a one-time code (TOTP)
    Then the admin console opens
    And the user exists in the realm master with the admin role
""")
def test_admin_identity_provider_login_gets_the_admin_role(
    page: Page,
    urls: dict[str, str],
    podiumd_env: Environment,
    credentials: SecretResolver,
    registry: ResourceRegistry,
) -> None:
    """An admin console login through the admin-role IdP, with TOTP enrolment, gives the brokered user admin."""
    username, password = credentials.optional("admin_idp_username"), credentials.optional("admin_idp_password")
    if not (username and password):
        pytest.skip("no test user of the admin identity provider: admin_idp_username, admin_idp_password")
    admin = for_environment(podiumd_env, "master")
    alias = str(_admin_role_providers(admin)[0]["alias"])
    # A brokered user of an earlier login holds an OTP credential, and the login would ask for a code instead.
    admin.delete_user_named(username)
    registry.add(f"brokered master realm user {username}", lambda: admin.delete_user_named(username))
    console = f"{urls['keycloak-admin']}/admin/master/console/"
    page.goto(console)
    page.locator(f"#social-{alias}").click()
    keycloak_login(page, username, password)
    configure_totp(page)
    page.wait_for_url(lambda url: url.startswith(console))
    user_id = admin.user_id(username)
    assert user_id, f"no brokered user {username} in the master realm after the login"
    assert "admin" in admin.user_realm_roles(user_id)
