"""Redis HA: redis-ha-master points at exactly the pod that is Redis' master, also after the master pod is deleted."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name
from podiumd_tests.redis import MASTER_LABEL
from podiumd_tests.redis import MASTER_SERVICE
from podiumd_tests.redis import checks_master_role
from podiumd_tests.redis import master_pod
from podiumd_tests.redis import ready_endpoints
from podiumd_tests.redis import redis_cli
from podiumd_tests.redis import redis_pods
from podiumd_tests.redis import reported_role
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import unhealthy_pods

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("cluster")]
STALE_LABEL = pytest.mark.source(
    "podiumd-tests",
    "helm-charts #634 (IN-2961): a stale master label on a replica must not make redis-ha-master point at a slave.",
)
# The StatefulSet recreates the pod and the operator reattaches the replicas (about 30 s on minikube).
RECOVERY_SECONDS = 180


@STALE_LABEL
def test_redis_ha_master_service_points_at_the_master(podiumd_env: Environment) -> None:
    """redis-ha-master has one ready endpoint, that pod reports role:master, and no master-labelled pod is a slave.

    The redis-operator skips NotReady pods when it fixes role labels, so a stale master label can stay on a replica;
    the readiness check of helm-charts #634 (masterReadinessCheck) keeps such a pod out of redis-ha-master.
    """
    pods = redis_pods(podiumd_env)
    if not pods:
        pytest.skip("no redis-ha pods")
    if not all(checks_master_role(p) for p in pods):
        pytest.skip("redis-ha has no masterReadinessCheck (helm-charts #634)")
    roles = {metadata_name(p): reported_role(podiumd_env, p) for p in pods}
    behind = ready_endpoints(podiumd_env, MASTER_SERVICE)
    assert len(behind) == 1, f"{MASTER_SERVICE} ready endpoints: {behind}"
    assert roles[behind[0]] == "master", roles
    labelled = [
        metadata_name(p) for p in pods if section(section(p, "metadata"), "labels").get(MASTER_LABEL) == "master"
    ]
    assert [p for p in labelled if roles[p] != "master"] == [], roles


@pytest.mark.destructive
@pytest.mark.usefixtures("several_replicas")
@pytest.mark.source(
    "podiumd-tests",
    "helm-charts #634 (IN-2961, IN-3225): after the master pod goes, redis-ha-master points at one master again.",
)
def test_redis_ha_master_recovers_when_the_master_pod_is_deleted(
    podiumd_env: Environment, registry: ResourceRegistry
) -> None:
    """After the master pod is deleted, redis-ha-master points at one master that kept the data, and all pods are ready.

    redis-operator promotes no replica while status.masterNode comes back: the recreated pod is master again.
    """
    pods = redis_pods(podiumd_env)
    if len(pods) < 2:
        pytest.skip("redis-ha runs one replica")
    master = master_pod(podiumd_env)
    assert master is not None, f"{MASTER_SERVICE} does not point at one master before the deletion"
    key = registry.tagged("redis-failover")
    assert redis_cli(podiumd_env, master, "SET", key, "kept").strip() == "OK"
    registry.add(f"redis key {key}", lambda: redis_cli(podiumd_env, master_pod(podiumd_env) or master, "DEL", key))
    uid = str(section(master, "metadata").get("uid"))
    podiumd_env.kube.delete("pod", metadata_name(master))
    recovered = wait_until(
        lambda: master_pod(podiumd_env, replaced_uid=uid),
        timeout=RECOVERY_SECONDS,
        description=f"a master behind {MASTER_SERVICE} other than the deleted pod",
    )
    assert redis_cli(podiumd_env, recovered, "GET", key).strip() == "kept"
    wait_until(
        lambda: len(redis_pods(podiumd_env)) == len(pods) and not unhealthy_pods(redis_pods(podiumd_env)),
        timeout=RECOVERY_SECONDS,
        description=f"{len(pods)} ready redis-ha pods",
    )
