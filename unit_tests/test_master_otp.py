"""Unit tests for requiring OTP in master's direct grant flow and master's service-account clients."""

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.auth import master_otp

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.seed.registry import ResourceRegistry

type Cleanup = tuple[str, Callable[[], object]]


class FakeRegistry:
    def __init__(self):
        self.cleanups: list[Cleanup] = []

    def add(self, what, cleanup):
        self.cleanups.append((what, cleanup))


def test_require_otp_makes_the_otp_subflow_required_and_restores_it(fake_master):
    master, registry = fake_master(), FakeRegistry()
    master_otp.require_otp(lambda: cast("KeycloakAdmin", master), cast("ResourceRegistry", registry))
    assert master.set == [("direct grant", "s", "REQUIRED"), ("direct grant", "c", "DISABLED")]
    assert master_otp.otp_requirement(master.executions) == master_otp.REQUIRED
    for _, cleanup in reversed(registry.cleanups):
        cleanup()
    assert master.set[2:] == [("direct grant", "c", "REQUIRED"), ("direct grant", "s", "CONDITIONAL")]
    assert master_otp.otp_requirement(master.executions) == master_otp.CONDITIONAL


@pytest.mark.parametrize(
    ("changes", "requirement"),
    [({"o": "DISABLED"}, "disabled"), ({"s": "DISABLED"}, "disabled"), ({"s": "REQUIRED"}, "required")],
)
def test_otp_requirement_follows_the_otp_execution_and_its_sub_flows(fake_master, changes, requirement):
    executions = fake_master().executions
    for execution in executions:
        execution["requirement"] = changes.get(execution["id"], execution["requirement"])
    assert master_otp.otp_requirement(executions) == requirement


def test_a_flow_without_otp_asks_for_none(fake_master):
    assert master_otp.otp_requirement(fake_master().executions[:1]) == master_otp.DISABLED


def test_service_admin_has_masters_admin_role_and_the_registry_deletes_it(fake_master, env_factory, monkeypatch):
    master, registry = fake_master(), FakeRegistry()
    monkeypatch.setattr(master_otp, "for_environment", lambda _env, realm: master if realm == "master" else None)
    logins = []
    monkeypatch.setattr(master_otp, "KeycloakAdmin", lambda _http, *args, **kwargs: logins.append((args, kwargs)))
    admin = master_otp.service_admin(env_factory(), cast("ResourceRegistry", registry))
    uuid = f"uuid-{master_otp.SERVICE_ADMIN}"
    assert master.roles == [(f"sa-{uuid}", ["admin"])]
    admin()
    login = ("https://kc-admin.example.test", "master", (master_otp.SERVICE_ADMIN, f"secret-{uuid}"))
    assert logins == [(login, {"is_client": True})]
    registry.cleanups[0][1]()
    assert master.clients == {}


def test_restore_operator_recreates_the_client_with_its_secret_only_when_absent(fake_master):
    master = fake_master()
    client = {"id": "old", "clientId": master_otp.OPERATOR, "serviceAccountsEnabled": True}
    master_otp.restore_operator(cast("KeycloakAdmin", master), client, "s3cr3t")
    master_otp.restore_operator(cast("KeycloakAdmin", master), client, "other")
    uuid = f"uuid-{master_otp.OPERATOR}"
    assert master.clients == {
        uuid: {"clientId": master_otp.OPERATOR, "serviceAccountsEnabled": True, "secret": "s3cr3t", "id": uuid}
    }
    assert master.roles == [(f"sa-{uuid}", ["admin"])]
