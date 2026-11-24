"""Keycloak's master realm with OTP required on every password grant, as some estates harden it (IN-3617)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
from podiumd_tests.auth.keycloak_admin import for_environment

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# A master service-account client: its client_credentials login does not run the direct grant flow.
SERVICE_ADMIN = "ptest-bootstrap-master-admin"
# Keycloak's built-in direct grant flow asks for OTP only when the user has one (condition "user configured").
CONDITION = "conditional-user-configured"
OTP = "direct-grant-validate-otp"


def service_admin(env: Environment, registry: ResourceRegistry) -> Callable[[], KeycloakAdmin]:
    """Create SERVICE_ADMIN with master's admin role; return a factory of master admin clients logged in with it.

    A factory: master's access tokens last one minute, and the registry restores the flow much later.
    """
    master = for_environment(env, "master")
    body = {
        "clientId": SERVICE_ADMIN,
        "publicClient": False,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
    }
    uuid = master.create_client(body)
    # A fresh login: master's token of now has expired by then, and the registry restores the flow first.
    registry.add(f"keycloak master client {SERVICE_ADMIN}", lambda: for_environment(env, "master").delete_client(uuid))
    master.add_realm_roles(master.service_account_user_id(uuid), master.realm_roles(("admin",)))
    secret = master.client_secret(uuid)
    return lambda: KeycloakAdmin(master.http, master.url, "master", (SERVICE_ADMIN, secret), is_client=True)


def require_otp(admin: Callable[[], KeycloakAdmin], registry: ResourceRegistry) -> None:
    """Make master's direct grant flow require OTP of every user; the registry restores the flow."""
    master = admin()
    flow = str(master.representation().get("directGrantFlow", "direct grant"))
    executions = master.flow_executions(flow)
    otp = next(index for index, execution in enumerate(executions) if execution.get("providerId") == OTP)
    changes = [(_parent(executions, otp), "REQUIRED")]
    changes += [(execution, "DISABLED") for execution in executions if execution.get("providerId") == CONDITION]
    for execution, requirement in changes:
        master.set_requirement(flow, execution, requirement)
        old = str(execution["requirement"])
        what = f"master {flow}: {execution['displayName']} back to {old}"
        registry.add(what, _restore(admin, flow, execution, old))


def _parent(executions: list[JsonObject], index: int) -> JsonObject:
    """Return the sub-flow that holds executions[index]: the nearest earlier execution one level up."""
    level = _level(executions[index])
    return next(execution for execution in reversed(executions[:index]) if _level(execution) < level)


def _level(execution: JsonObject) -> int:
    return int(str(execution["level"]))


def _restore(
    admin: Callable[[], KeycloakAdmin], flow: str, execution: JsonObject, requirement: str
) -> Callable[[], None]:
    return lambda: admin().set_requirement(flow, execution, requirement)
