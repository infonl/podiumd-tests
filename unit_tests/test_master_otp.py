"""Unit tests for requiring OTP in master's direct grant flow."""

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth import master_otp

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.seed.registry import ResourceRegistry

type Cleanup = tuple[str, Callable[[], object]]

EXECUTIONS = [
    {
        "id": "u",
        "level": 0,
        "displayName": "Username Validation",
        "providerId": "direct-grant-validate-username",
        "requirement": "REQUIRED",
    },
    {
        "id": "p",
        "level": 0,
        "displayName": "Password",
        "providerId": "direct-grant-validate-password",
        "requirement": "REQUIRED",
    },
    {"id": "s", "level": 0, "displayName": "Direct Grant - Conditional OTP", "requirement": "CONDITIONAL"},
    {
        "id": "c",
        "level": 1,
        "displayName": "Condition - user configured",
        "providerId": master_otp.CONDITION,
        "requirement": "REQUIRED",
    },
    {"id": "o", "level": 1, "displayName": "OTP", "providerId": master_otp.OTP, "requirement": "REQUIRED"},
]


class FakeMaster:
    def __init__(self):
        self.flow: str = "direct grant"
        self.set: list[tuple[str, str, str]] = []

    def representation(self):
        return {"directGrantFlow": self.flow}

    def flow_executions(self, flow):
        return EXECUTIONS if flow == self.flow else []

    def set_requirement(self, flow, execution, requirement):
        self.set.append((flow, execution["id"], requirement))


class FakeRegistry:
    def __init__(self):
        self.cleanups: list[Cleanup] = []

    def add(self, what, cleanup):
        self.cleanups.append((what, cleanup))


def test_require_otp_makes_the_otp_subflow_required_and_restores_it():
    master, registry = FakeMaster(), FakeRegistry()
    master_otp.require_otp(lambda: cast("KeycloakAdmin", master), cast("ResourceRegistry", registry))
    assert master.set == [("direct grant", "s", "REQUIRED"), ("direct grant", "c", "DISABLED")]
    for _, cleanup in reversed(registry.cleanups):
        cleanup()
    assert master.set[2:] == [("direct grant", "c", "REQUIRED"), ("direct grant", "s", "CONDITIONAL")]
