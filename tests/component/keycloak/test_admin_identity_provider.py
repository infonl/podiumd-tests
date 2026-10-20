"""An admin identity provider that grants a Keycloak admin role must allow admin role mapping.

Keycloak 26.8 (CVE-2026-12388) refuses an oidc-hardcoded-role-idp-mapper that grants an admin role unless the
identity provider has config.allowAdminRoleMapping "true"; the master realm import then fails (podiumd-chart-17,
helm-charts #623). The import succeeds here, so the config must be consistent. Environments without an admin
identity provider (minikube before the stand-in) skip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("keycloak-admin")]

# Hardcoded-role mapper types, and the master realm role names that are admin by name.
ROLE_MAPPER = "oidc-hardcoded-role-idp-mapper"
ADMIN_ROLES = frozenset({"admin"})


def _grants_admin(mapper: JsonObject) -> bool:
    config = mapper.get("config") or {}
    role = str(config.get("role", "")) if isinstance(config, dict) else ""
    return mapper.get("identityProviderMapper") == ROLE_MAPPER and role.rsplit(".", maxsplit=1)[-1] in ADMIN_ROLES


def test_admin_role_identity_provider_allows_admin_role_mapping(podiumd_env: Environment) -> None:
    """Every master-realm IdP whose mapper grants the admin role has config.allowAdminRoleMapping true."""
    admin = for_environment(podiumd_env, "master")
    providers = admin.identity_providers()
    if not providers:
        pytest.skip("no identity provider in the master realm")
    offenders = []
    checked = 0
    for provider in providers:
        alias = str(provider["alias"])
        if not any(_grants_admin(m) for m in admin.identity_provider_mappers(alias)):
            continue
        checked += 1
        config = provider.get("config") or {}
        allow = str(config.get("allowAdminRoleMapping", "")) if isinstance(config, dict) else ""
        if allow != "true":
            offenders.append(f"{alias}: allowAdminRoleMapping={allow or 'unset'}")
    if not checked:
        pytest.skip("no identity provider grants a Keycloak admin role")
    assert not offenders, f"admin-role identity providers without allowAdminRoleMapping: {offenders}"
