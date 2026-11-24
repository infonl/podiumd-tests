"""The keycloak-operator service account in master, also where master requires OTP on every password grant."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth import master_otp
from podiumd_tests.auth.keycloak import client_credentials_grant
from podiumd_tests.defects import DefectSymptomError
from podiumd_tests.defects import symptom
from podiumd_tests.kube import KubeError
from podiumd_tests.workloads import release_object
from podiumd_tests.workloads import rerun_job

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("cluster", "keycloak", "keycloak-admin")]

OPERATOR = master_otp.OPERATOR
OPERATOR_JOB = "ensure-keycloak-operator-sa"
# The Job's wait for podiumd-admin alone takes up to 60 tries of 10 s.
JOB_SECONDS = 900


def remove_operator_client(admin: Callable[[], KeycloakAdmin], registry: ResourceRegistry) -> None:
    """Delete master's keycloak-operator client; the registry recreates it, with its secret, when it is still gone."""
    master = admin()
    client = master.client(OPERATOR)
    if client is None:
        pytest.skip(f"master has no {OPERATOR} client")
    secret = master.client_secret(str(client["id"]))
    registry.add(f"keycloak master client {OPERATOR}", lambda: master_otp.restore_operator(admin(), client, secret))
    master.delete_client(str(client["id"]))


@pytest.mark.destructive
@pytest.mark.source(
    "podiumd-tests",
    "Jira IN-3617: an upgrade hung on the Keycloak jobs where master requires OTP and the operator client was missing.",
)
@pytest.mark.xfail(
    strict=True,
    raises=DefectSymptomError,
    reason="[podiumd-chart-55] podiumd 4.9.6 to 4.11.0: without the keycloak-operator client the Job falls back to a"
    " password login as podiumd-admin, which a master realm that requires OTP answers with 500; the Job retries"
    " until it times out; not reported upstream",
)
@pytest.mark.scenario("""
    Given Keycloak's master realm asks every password login for a one-time code
    And the Keycloak operator's service account is missing
    When the chart's job that sets up that service account runs
    Then it completes
    And the operator can log in with its service account
""")
def test_operator_service_account_is_set_up_when_master_requires_otp(
    podiumd_env: Environment, registry: ResourceRegistry
) -> None:
    """ensure-keycloak-operator-sa recreates the operator's client although master requires OTP on password grants."""
    source = release_object(podiumd_env, "Job", OPERATOR_JOB)
    if source is None:
        pytest.skip(f"no Job {OPERATOR_JOB} in the Helm release: the chart renders it only with ensureOperatorSa")
    admin = master_otp.service_admin(podiumd_env, registry)
    remove_operator_client(admin, registry)
    master_otp.require_otp(admin, registry)
    job = registry.tagged("ensure-operator-sa")
    with symptom():
        try:
            rerun_job(podiumd_env.kube, source, job, JOB_SECONDS)
        except KubeError as error:
            msg = f"{OPERATOR_JOB} did not complete within {JOB_SECONDS} s: {error}"
            raise AssertionError(msg) from error
    client = admin().client(OPERATOR)
    assert client is not None, f"{OPERATOR_JOB} completed without creating master's {OPERATOR} client"
    secret = admin().client_secret(str(client["id"]))
    client_credentials_grant(podiumd_env.session(cookies=False), admin().url, "master", (OPERATOR, secret))
