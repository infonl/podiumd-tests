"""Redis HA: redis-ha-master points at exactly the pod that is Redis' master, also when the master pod or node goes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.defects import DefectSymptomError
from podiumd_tests.defects import symptom
from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name
from podiumd_tests.redis import MASTER_LABEL
from podiumd_tests.redis import MASTER_SERVICE
from podiumd_tests.redis import TAKEOVER_SECONDS
from podiumd_tests.redis import is_master_role_checked
from podiumd_tests.redis import master_pod
from podiumd_tests.redis import redis_cli
from podiumd_tests.redis import redis_pods
from podiumd_tests.redis import reported_role
from podiumd_tests.redis import sentinel_pods
from podiumd_tests.redis import wait_for_takeover
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import ready_endpoints
from podiumd_tests.workloads import unhealthy_pods

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.redis import Takeover
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("cluster")]
STALE_LABEL = pytest.mark.source(
    "podiumd-tests",
    "helm-charts #634 (IN-2961): a stale master label on a replica must not make redis-ha-master point at a slave.",
)
# The StatefulSet recreates the pod and the operator reattaches the replicas (about 30 s on minikube); on another
# node the pod's zonal disk must attach first.
RECOVERY_SECONDS = 300
FAILOVER_SOURCE = pytest.mark.source(
    "podiumd-tests",
    "podiumd-chart-24 (Jira IN-2869, IN-3210): a replica takes over when the master pod or its node goes.",
)
NO_FAILOVER = pytest.mark.xfail(
    strict=True,
    raises=DefectSymptomError,
    reason="[podiumd-chart-24] podiumd 4.10.1 and 4.11.0 run redis-ha (redis-operator 0.27.0) without Sentinel: no"
    " replica takes over, redis-ha-master waits for the recreated master pod; scheduled for PodiumD 4.11",
)


@STALE_LABEL
@pytest.mark.scenario("""
    Given Redis HA with the master readiness check
    When the roles the redis-ha pods report are read
    Then the service redis-ha-master has exactly one ready pod
    And that pod reports the role master
    And no pod labelled master reports another role
""")
def test_redis_ha_master_service_points_at_the_master(podiumd_env: Environment) -> None:
    """redis-ha-master has one ready endpoint, that pod reports role:master, and no master-labelled pod is a slave.

    The redis-operator skips NotReady pods when it fixes role labels, so a stale master label can stay on a replica;
    the readiness check of helm-charts #634 (masterReadinessCheck) keeps such a pod out of redis-ha-master.
    """
    pods = redis_pods(podiumd_env)
    if not pods:
        pytest.skip("no redis-ha pods")
    if not all(is_master_role_checked(p) for p in pods):
        pytest.skip("redis-ha has no masterReadinessCheck (helm-charts #634)")
    roles = {metadata_name(p): reported_role(podiumd_env, p) for p in pods}
    behind = ready_endpoints(podiumd_env, MASTER_SERVICE)
    assert len(behind) == 1, f"{MASTER_SERVICE} ready endpoints: {behind}"
    assert roles[behind[0]] == "master", roles
    labelled = [
        metadata_name(p) for p in pods if section(section(p, "metadata"), "labels").get(MASTER_LABEL) == "master"
    ]
    assert [p for p in labelled if roles[p] != "master"] == [], roles


def fail_over(
    env: Environment, registry: ResourceRegistry, stop: Callable[[JsonObject], object]
) -> tuple[str, Takeover]:
    """Store a key on the master, stop it, and wait until a master that kept the key and all redis-ha pods are back.

    Returns the stopped master's name and the takeover; redis-ha-master never points at two pods or a replica.
    """
    pods = redis_pods(env)
    if len(pods) < 2:
        pytest.skip("redis-ha runs one replica")
    master = master_pod(env)
    assert master is not None, f"{MASTER_SERVICE} does not point at one master before the failover"
    key = registry.tagged("redis-failover")
    assert redis_cli(env, master, "SET", key, "kept").strip() == "OK"
    registry.add(f"redis key {key}", lambda: redis_cli(env, master_pod(env) or master, "DEL", key))
    stop(master)
    takeover = wait_for_takeover(env, str(section(master, "metadata").get("uid")), RECOVERY_SECONDS)
    assert redis_cli(env, takeover.master, "GET", key).strip() == "kept"
    assert takeover.problems == []
    wait_until(
        lambda: len(redis_pods(env)) == len(pods) and not unhealthy_pods(redis_pods(env)),
        timeout=RECOVERY_SECONDS,
        description=f"{len(pods)} ready redis-ha pods",
    )
    return metadata_name(master), takeover


def expect_takeover(env: Environment, stopped: str, takeover: Takeover) -> None:
    """A replica, not the recreated pod, became master within TAKEOVER_SECONDS, and the stopped pod is a replica now."""
    with symptom():
        new = metadata_name(takeover.master)
        assert new != stopped, f"{stopped} is master again after {takeover.seconds} s: no replica took over"
        assert takeover.seconds <= TAKEOVER_SECONDS, f"{new} took over after {takeover.seconds} s"
        returned = next(pod for pod in redis_pods(env) if metadata_name(pod) == stopped)
        assert reported_role(env, returned) == "slave", f"{stopped} came back as {reported_role(env, returned)}"


@pytest.mark.destructive
@pytest.mark.usefixtures("several_replicas")
@pytest.mark.source(
    "podiumd-tests",
    "helm-charts #634 (IN-2961, IN-3225): after the master pod goes, redis-ha-master points at one master again.",
)
@FAILOVER_SOURCE
@NO_FAILOVER
@pytest.mark.scenario("""
    Given Redis HA runs several replicas
    And a key is stored on the master
    When the master pod is deleted
    Then a replica becomes master within 30 seconds and still holds the key
    And redis-ha-master never points at two pods or at a replica
    And the deleted pod comes back as a replica
""")
def test_a_replica_takes_over_when_the_master_pod_is_deleted(
    podiumd_env: Environment, registry: ResourceRegistry
) -> None:
    """After the master pod is deleted, a replica that kept the data is master, and all pods are ready again."""
    stopped, takeover = fail_over(
        podiumd_env, registry, lambda master: podiumd_env.kube.delete("pod", metadata_name(master))
    )
    expect_takeover(podiumd_env, stopped, takeover)


@pytest.mark.destructive
@FAILOVER_SOURCE
@NO_FAILOVER
@pytest.mark.scenario("""
    Given Redis HA runs on several nodes
    And a key is stored on the master
    When the master's node is cordoned and the master pod is evicted from it
    Then a replica becomes master within 30 seconds and still holds the key
    And redis-ha-master never points at two pods or at a replica
""")
def test_a_replica_takes_over_when_the_master_node_is_drained(
    podiumd_env: Environment, registry: ResourceRegistry
) -> None:
    """With the master's node cordoned and the master pod deleted, a replica takes over; the pod moves elsewhere."""
    if len(podiumd_env.kube.items("nodes")) < 2:
        pytest.skip(f"{podiumd_env.profile.name} has one node")

    def drain(master: JsonObject) -> None:
        node = str(section(master, "spec").get("nodeName"))
        podiumd_env.kube.run("cordon", node)
        registry.add(f"uncordon {node}", lambda: podiumd_env.kube.run("uncordon", node))
        podiumd_env.kube.delete("pod", metadata_name(master))

    stopped, takeover = fail_over(podiumd_env, registry, drain)
    expect_takeover(podiumd_env, stopped, takeover)


@pytest.mark.destructive
@pytest.mark.usefixtures("several_replicas")
@FAILOVER_SOURCE
@pytest.mark.scenario("""
    Given Redis HA runs several replicas with Sentinel
    And a key is stored on the master
    When the master pod and one Sentinel are deleted together
    Then a replica becomes master within 30 seconds and still holds the key
    And redis-ha-master never points at two pods or at a replica
""")
def test_a_replica_takes_over_when_the_master_and_a_sentinel_go(
    podiumd_env: Environment, registry: ResourceRegistry
) -> None:
    """With the master pod and one Sentinel deleted, the remaining Sentinels let a replica take over."""
    sentinels = sentinel_pods(podiumd_env)
    if len(sentinels) < 2:
        pytest.skip(f"redis-ha has {len(sentinels)} Sentinel pods (podiumd-chart-24)")

    def stop(master: JsonObject) -> None:
        podiumd_env.kube.delete("pod", metadata_name(sentinels[0]))
        podiumd_env.kube.delete("pod", metadata_name(master))

    stopped, takeover = fail_over(podiumd_env, registry, stop)
    expect_takeover(podiumd_env, stopped, takeover)
