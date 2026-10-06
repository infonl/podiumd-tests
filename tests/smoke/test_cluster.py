"""Are the workloads up? Ported from MK/PI test_pods.py (see podiumd_tests.workloads)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.workloads import failed_jobs
from podiumd_tests.workloads import unhealthy_pods
from podiumd_tests.workloads import unready_workloads

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.smoke, pytest.mark.cluster, pytest.mark.requires("cluster")]


def _items(podiumd_env: Environment, kind: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for namespace in podiumd_env.namespaces:
        items += podiumd_env.kube.items(kind, namespace=namespace)
    return items


def test_workloads_ready(podiumd_env: Environment) -> None:
    """Every Deployment and StatefulSet has all wanted replicas ready."""
    not_ready = unready_workloads(_items(podiumd_env, "deployments") + _items(podiumd_env, "statefulsets"))
    assert not not_ready, f"not ready: {not_ready}"


def test_pods_healthy(podiumd_env: Environment) -> None:
    """Every long-running pod is Running with all containers ready (catches a stuck 1/2 sidecar)."""
    unhealthy = unhealthy_pods(_items(podiumd_env, "pods"))
    assert not unhealthy, f"unhealthy pods: {unhealthy}"


def test_jobs_succeeded(podiumd_env: Environment) -> None:
    """No setup Job failed, and the latest run of each CronJob did not fail."""
    failed = failed_jobs(_items(podiumd_env, "jobs"))
    assert not failed, f"failed jobs: {failed}"
