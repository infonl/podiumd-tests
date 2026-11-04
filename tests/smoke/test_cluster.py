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
from podiumd_tests.workloads import KEYCLOAKS
from podiumd_tests.workloads import chart_older_than
from podiumd_tests.workloads import failed_jobs
from podiumd_tests.workloads import replica_drift
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
@pytest.mark.scenario("""
    When the environment's Deployments and StatefulSets are read
    Then each has all its wanted replicas ready
""")
def test_workloads_ready(podiumd_env: Environment) -> None:
    """Every Deployment and StatefulSet has all wanted replicas ready."""
    not_ready = unready_workloads(podiumd_env.workloads())
    assert not not_ready, f"not ready: {not_ready}"


@pytest.mark.source(
    "podiumd-tests",
    "A chaos test that scales a component to 0 and is stopped before it restores it leaves the component down.",
)
@pytest.mark.scenario("""
    When the Deployments and StatefulSets of the Helm releases are read
    Then each runs the number of replicas its release sets
""")
def test_workloads_have_their_helm_replicas(podiumd_env: Environment) -> None:
    """Every Deployment and StatefulSet of a Helm release runs the replicas its release sets."""
    drift = replica_drift(podiumd_env)
    assert not drift, f"replicas differ from Helm: {drift}"


@pytest.mark.source(
    "MK test_pods.py",
    "Pod health after every deploy: every pod Running with all containers Ready, or Succeeded for one-shot Jobs.",
)
@pytest.mark.source(
    "PI test_pods.py",
    "Pod health checks adapted from podiumd-minikube for a real podiumd-infra estate's pod set.",
)
@pytest.mark.scenario("""
    When the environment's long-running pods are read
    Then each pod is Running with all its containers ready
""")
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
@pytest.mark.scenario("""
    When the environment's Jobs are read
    Then no setup Job failed
    And the latest run of each CronJob did not fail
""")
def test_jobs_succeeded(podiumd_env: Environment) -> None:
    """No setup Job failed, and the latest run of each CronJob did not fail."""
    keycloaks = podiumd_env.items(KEYCLOAKS) if "keycloak-operator" in podiumd_env.deployment_names else []
    failed = failed_jobs(podiumd_env.items("jobs"), keycloaks)
    assert not failed, f"failed jobs: {failed}"


@pytest.mark.source(
    "podiumd-tests",
    "Pod templates meet the Kubernetes Pod Security Standard baseline: no host access, privileged or capabilities.",
)
@pytest.mark.scenario("""
    When the pod templates of the environment's workloads are read
    Then none uses host namespaces, host paths or host ports
    And none runs privileged or adds capabilities
""")
def test_pods_meet_the_baseline_security_standard(podiumd_env: Environment) -> None:
    """No pod template uses host namespaces, host paths or ports, privileged mode or extra capabilities."""
    found = [v for w in podiumd_env.workloads() for v in baseline_violations(w)]
    assert not found, found


@pytest.mark.source(
    "podiumd-tests",
    "Flags images without a tag or tagged latest, so a restart cannot change what runs.",
)
@pytest.mark.scenario("""
    When the images of the environment's workloads are read
    Then each has a tag other than latest, or a digest
""")
def test_images_are_pinned(podiumd_env: Environment) -> None:
    """Every image has a tag other than latest, or a digest, so a restart cannot change what runs."""
    found = [i for w in podiumd_env.workloads() for i in unpinned_images(w)]
    assert not found, found


@pytest.mark.source(
    "podiumd-tests",
    "Flags containers without a CPU or memory request, so the scheduler places them by size.",
)
@pytest.mark.scenario("""
    When the containers of the environment's workloads are read
    Then each requests CPU and memory
""")
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
@pytest.mark.scenario("""
    Given Keycloak runs more than one instance
    When the PodDisruptionBudgets are read
    Then one covers Keycloak's instances
""")
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
@pytest.mark.usefixtures("several_replicas")
@pytest.mark.scenario("""
    Given Redis HA runs more than one replica
    When the PodDisruptionBudgets are read
    Then one covers the redis-ha replicas
""")
def test_redis_ha_replicas_have_a_disruption_budget(request: pytest.FixtureRequest, podiumd_env: Environment) -> None:
    """redis-ha's replicas have a PodDisruptionBudget (redis-ha-replication), so a node drain keeps one running."""
    if chart_older_than(podiumd_env, (4, 10, 0)):
        request.applymarker(
            pytest.mark.xfail(
                strict=True,
                reason="podiumd before 4.10.0 has no PodDisruptionBudget for redis-ha (redis-operator.redis-ha.pdb,"
                " helm-charts #634)",
            )
        )
    redis = [w for w in podiumd_env.workloads() if metadata_name(w) == REDIS_HA]
    if not redis or all(section(w, "spec").get("replicas", 1) == 1 for w in redis):
        pytest.skip("redis-ha runs one replica")
    assert not without_disruption_budget(redis, podiumd_env.items("poddisruptionbudgets"))
