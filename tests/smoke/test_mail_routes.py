"""Mail stays inside the cluster: minikube and QA (podiumd-infra) never send to a real SMTP server."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.mail_routes import cluster_hosts
from podiumd_tests.mail_routes import is_internal
from podiumd_tests.mail_routes import mail_stays_internal
from podiumd_tests.mail_routes import realm_routes
from podiumd_tests.mail_routes import workload_routes

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment
    from podiumd_tests.mail_routes import MailRoute

pytestmark = [pytest.mark.smoke, pytest.mark.cluster, pytest.mark.requires("cluster")]


@pytest.fixture(scope="module", name="internal")
def fixture_internal(podiumd_env: Environment) -> frozenset[str]:
    """The hosts mail may go to; skips where the estate has no such rule."""
    if not mail_stays_internal(podiumd_env.profile):
        pytest.skip(f"estate {podiumd_env.profile.estate} has no in-cluster mail rule")
    return cluster_hosts(podiumd_env)


def outside(routes: list[MailRoute], internal: frozenset[str]) -> list[str]:
    """The routes to a host outside the cluster."""
    return [f"{r.where} = {r.host}" for r in routes if not is_internal(r.host, internal)]


def test_workloads_send_mail_only_inside_the_cluster(podiumd_env: Environment, internal: frozenset[str]) -> None:
    """Every SMTP host a container gets is a cluster Service or no server."""
    assert not outside(workload_routes(podiumd_env), internal)


@pytest.mark.requires("keycloak")
def test_keycloak_realms_send_mail_only_inside_the_cluster(podiumd_env: Environment, internal: frozenset[str]) -> None:
    """The login realm and master send mail to a cluster Service, or not at all."""
    admins = [for_environment(podiumd_env), for_environment(podiumd_env, "master")]
    assert not outside(realm_routes(admins), internal)
