"""Are the workloads up and deployed with care? Ported from MK/PI test_pods.py (see workloads, hygiene)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.hygiene import baseline_violations
from podiumd_tests.hygiene import missing_requests
from podiumd_tests.hygiene import unpinned_images
from podiumd_tests.hygiene import without_disruption_budget
from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name
from podiumd_tests.redis import REDIS_HA
from podiumd_tests.workloads import failed_jobs
from podiumd_tests.workloads import unhealthy_pods
from podiumd_tests.workloads import unready_workloads

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.smoke, pytest.mark.cluster, pytest.mark.requires("cluster")]


@pytest.mark.source(
    "MK test_pods.py",
    "Pod health after every deploy: every pod Running with all containers Ready, or Succeeded for one-shot Jobs.",
)
@pytest.mark.source(
    "PI test_pods.py",
    "Pod health checks adapted from podiumd-minikube for a real podiumd-infra estate's pod set.",
)
@pytest.mark.source(
    "TA smoke/00-environment-preflight.spec.ts",
    "Preflight that detects dead infrastructure before the suite runs; 00f checks the ZAC pod is 2/2 Ready.",
)
@pytest.mark.source(
    "EX tests/smoke/00-environment-preflight.spec.ts",
    "Preflight that detects dead infrastructure before the suite runs; 00f checks the ZAC pod is 2/2 Ready.",
)
def test_workloads_ready(podiumd_env: Environment) -> None:
    """Every Deployment and StatefulSet has all wanted replicas ready."""
    not_ready = unready_workloads(podiumd_env.workloads())
    assert not not_ready, f"not ready: {not_ready}"


@pytest.mark.source(
    "MK test_pods.py",
    "Pod health after every deploy: every pod Running with all containers Ready, or Succeeded for one-shot Jobs.",
)
@pytest.mark.source(
    "PI test_pods.py",
    "Pod health checks adapted from podiumd-minikube for a real podiumd-infra estate's pod set.",
)
def test_pods_healthy(podiumd_env: Environment) -> None:
    """Every long-running pod is Running with all containers ready (catches a stuck 1/2 sidecar)."""
    unhealthy = unhealthy_pods(podiumd_env.items("pods"))
    assert not unhealthy, f"unhealthy pods: {unhealthy}"


@pytest.mark.source(
    "MK test_pods.py",
    "Pod health after every deploy: every pod Running with all containers Ready, or Succeeded for one-shot Jobs.",
)
@pytest.mark.source(
    "PI test_pods.py",
    "Pod health checks adapted from podiumd-minikube for a real podiumd-infra estate's pod set.",
)
def test_jobs_succeeded(podiumd_env: Environment) -> None:
    """No setup Job failed, and the latest run of each CronJob did not fail."""
    failed = failed_jobs(podiumd_env.items("jobs"))
    assert not failed, f"failed jobs: {failed}"


@pytest.mark.source(
    "podiumd-tests",
    "Pod templates meet the Kubernetes Pod Security Standard baseline: no host access, privileged or capabilities.",
)
def test_pods_meet_the_baseline_security_standard(podiumd_env: Environment) -> None:
    """No pod template uses host namespaces, host paths or ports, privileged mode or extra capabilities."""
    found = [v for w in podiumd_env.workloads() for v in baseline_violations(w)]
    assert not found, found


@pytest.mark.source(
    "podiumd-tests",
    "Flags images without a tag or tagged latest, so a restart cannot change what runs.",
)
def test_images_are_pinned(podiumd_env: Environment) -> None:
    """Every image has a tag other than latest, or a digest, so a restart cannot change what runs."""
    found = [i for w in podiumd_env.workloads() for i in unpinned_images(w)]
    assert not found, found


@pytest.mark.source(
    "podiumd-tests",
    "Flags containers without a CPU or memory request, so the scheduler places them by size.",
)
def test_containers_request_cpu_and_memory(podiumd_env: Environment) -> None:
    """Every container requests CPU and memory, so the scheduler places it by size."""
    found = [m for w in podiumd_env.workloads() for m in missing_requests(w)]
    assert not found, sorted(set(found))


@pytest.mark.source(
    "podiumd-tests",
    "Keycloak with more than one replica needs a PodDisruptionBudget, so a node drain keeps one instance running.",
)
@pytest.mark.requires("keycloak")
# Not strict: an estate that sets keycloak.podDisruptionBudget.enabled passes.
@pytest.mark.xfail(
    strict=False,
    reason="[podiumd-chart-7] podiumd 4.10.0's Keycloak PodDisruptionBudget is off by default"
    " (keycloak.podDisruptionBudget.enabled), so a node drain can stop both instances",
)
@pytest.mark.usefixtures("several_replicas")
def test_keycloak_instances_have_a_disruption_budget(podiumd_env: Environment) -> None:
    """Keycloak's instances have a PodDisruptionBudget, so a node drain keeps one running."""
    keycloak = [w for w in podiumd_env.workloads() if metadata_name(w) == "keycloak"]
    if not keycloak or all(section(w, "spec").get("replicas", 1) == 1 for w in keycloak):
        pytest.skip("Keycloak runs one instance")
    assert not without_disruption_budget(keycloak, podiumd_env.items("poddisruptionbudgets"))


@pytest.mark.source(
    "podiumd-tests",
    "helm-charts #634 (IN-2961, IN-3225): redis-ha's replicas need a PodDisruptionBudget, so a node drain keeps a master.",
)
# Not strict: an environment with helm-charts #634 passes.
@pytest.mark.xfail(
    strict=False,
    reason="helm-charts #634 (podiumd 4.10.0) adds redis-operator.redis-ha.pdb; before it no PodDisruptionBudget selects redis-ha",
)
@pytest.mark.usefixtures("several_replicas")
def test_redis_ha_replicas_have_a_disruption_budget(podiumd_env: Environment) -> None:
    """redis-ha's replicas have a PodDisruptionBudget (redis-ha-replication), so a node drain keeps one running."""
    redis = [w for w in podiumd_env.workloads() if metadata_name(w) == REDIS_HA]
    if not redis or all(section(w, "spec").get("replicas", 1) == 1 for w in redis):
        pytest.skip("redis-ha runs one replica")
    assert not without_disruption_budget(redis, podiumd_env.items("poddisruptionbudgets"))
