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
# The Keycloak operator's service-account client in master, which the chart's ensure-keycloak-operator-sa Job creates.
OPERATOR = "keycloak-operator"
# Keycloak's built-in direct grant flow asks for OTP only when the user has one (condition "user configured").
CONDITION = "conditional-user-configured"
OTP = "direct-grant-validate-otp"
REQUIRED = "required"
CONDITIONAL = "conditional"
DISABLED = "disabled"

type Change = tuple[JsonObject, str]


def create_service_admin(master: KeycloakAdmin, created: Callable[[str], object]) -> str:
    """Create SERVICE_ADMIN with master's admin role; return its secret. created(uuid) runs right after the create."""
    body = {
        "clientId": SERVICE_ADMIN,
        "publicClient": False,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
    }
    uuid = master.create_client(body)
    created(uuid)
    master.add_realm_roles(master.service_account_user_id(uuid), master.realm_roles(("admin",)))
    return master.client_secret(uuid)


def service_admin_login(master: KeycloakAdmin, secret: str) -> Callable[[], KeycloakAdmin]:
    """Return a factory of master admin clients logged in as SERVICE_ADMIN.

    A factory: master's access tokens last one minute.
    """
    return lambda: KeycloakAdmin(master.http, master.url, "master", (SERVICE_ADMIN, secret), is_client=True)


def service_admin(env: Environment, registry: ResourceRegistry) -> Callable[[], KeycloakAdmin]:
    """Create SERVICE_ADMIN; return a factory of master admin clients logged in with it. The registry deletes it."""
    master = for_environment(env, "master")

    def created(uuid: str) -> None:
        # A fresh login: master's token of now has expired by then, and the registry restores the flow first.
        what = f"keycloak master client {SERVICE_ADMIN}"
        registry.add(what, lambda: for_environment(env, "master").delete_client(uuid))

    return service_admin_login(master, create_service_admin(master, created))


def otp_changes(master: KeycloakAdmin) -> tuple[str, list[Change]]:
    """Return master's direct grant flow and the (execution, requirement) changes that make it require OTP of all."""
    flow = direct_grant_flow(master)
    executions = master.flow_executions(flow)
    otp = _otp_index(executions)
    if otp is None:
        msg = f"master's flow {flow} has no {OTP} execution"
        raise LookupError(msg)
    changes = [(_parent(executions, otp), "REQUIRED")]
    changes += [(execution, "DISABLED") for execution in executions if execution.get("providerId") == CONDITION]
    return flow, changes


def require_otp(admin: Callable[[], KeycloakAdmin], registry: ResourceRegistry) -> None:
    """Make master's direct grant flow require OTP of every user; the registry restores the flow."""
    master = admin()
    flow, changes = otp_changes(master)
    for execution, requirement in changes:
        master.set_requirement(flow, execution, requirement)
        old = str(execution["requirement"])
        what = f"master {flow}: {execution['displayName']} back to {old}"
        registry.add(what, _restore(admin, flow, execution, old))


def direct_grant_flow(master: KeycloakAdmin) -> str:
    """Return the alias of the realm's direct grant flow."""
    return str(master.representation().get("directGrantFlow", "direct grant"))


def otp_requirement(executions: list[JsonObject]) -> str:
    """Return REQUIRED, CONDITIONAL or DISABLED: whether a direct grant flow's executions ask every user for OTP.

    Required only when the OTP execution and every sub-flow above it are REQUIRED.
    """
    index = _otp_index(executions)
    if index is None:
        return DISABLED
    chain = [executions[index]]
    while _level(chain[-1]) > 0:
        chain.append(_parent(executions, executions.index(chain[-1])))
    requirements = {str(execution.get("requirement")) for execution in chain}
    if "DISABLED" in requirements:
        return DISABLED
    return REQUIRED if requirements == {"REQUIRED"} else CONDITIONAL


def restore_operator(master: KeycloakAdmin, client: JsonObject, secret: str) -> None:
    """Recreate master's OPERATOR client with its secret and master's admin role, unless it exists."""
    if master.client(OPERATOR) is not None:
        return
    body = {key: value for key, value in client.items() if key != "id"}
    uuid = master.create_client({**body, "secret": secret})
    master.add_realm_roles(master.service_account_user_id(uuid), master.realm_roles(("admin",)))


def _otp_index(executions: list[JsonObject]) -> int | None:
    providers = [execution.get("providerId") for execution in executions]
    return providers.index(OTP) if OTP in providers else None


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
