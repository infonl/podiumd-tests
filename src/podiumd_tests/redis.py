"""Redis HA of the podiumd chart (redis-operator): its pods, the role each reports, and the Deployments using it."""

from __future__ import annotations

import re
import shlex
import time

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from podiumd_tests.components import COMPONENTS
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_labels
from podiumd_tests.kube import metadata_name
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import ready_endpoints
from podiumd_tests.workloads import replace_pod
from podiumd_tests.workloads import variable_config_maps

if TYPE_CHECKING:
    from collections.abc import Collection

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

# The redis-operator's StatefulSet, Services and container of the podiumd chart.
REDIS_HA = "redis-ha"
MASTER_SERVICE = "redis-ha-master"
# The custom resource that owns the StatefulSet, and the operator's Deployment.
OWNER_KIND = "RedisReplication"
OPERATOR = "redis-operator"
# The operator labels the pod it made master; redis-ha-master selects that label.
MASTER_LABEL = "redis-role"
# The operator's Sentinel StatefulSet of redis-ha, once the chart renders one (podiumd-chart-24).
SENTINEL = "redis-ha-sentinel"
# A replica takes over within this many seconds of the master pod or its node going (podiumd-chart-24).
TAKEOVER_SECONDS = 30
# REDISCLI_AUTH is the pods' own password variable, set only when Redis has one.
REDIS_CLI = "redis-cli -h $(hostname) -p ${REDIS_PORT:-6379}"


def redis_deployments(env: Environment) -> list[str]:
    """Return the Deployments that read MASTER_SERVICE from a ConfigMap (CACHE_*, CELERY_BROKER_URL)."""
    data = {metadata_name(item): section(item, "data") for item in env.kube.items("configmaps")}

    def is_redis_user(deployment: JsonObject) -> bool:
        values = (value for name in variable_config_maps(deployment) for value in data.get(name, {}).values())
        return any(MASTER_SERVICE in str(value) for value in values)

    return sorted(metadata_name(item) for item in env.kube.items("deployments") if is_redis_user(item))


def redis_components(env: Environment, deployments: Collection[str]) -> list[str]:
    """Return the present components whose main Deployment is one of `deployments`."""
    present = sorted(component for component in COMPONENTS if component in env.capabilities.present)
    found: list[str] = []
    for component in present:
        with suppress(KubeError):  # a component without a main Deployment
            if env.deployment_for(component) in deployments:
                found.append(component)
    return found


def redis_pods(env: Environment) -> list[JsonObject]:
    """Return the pods of the redis-ha StatefulSet."""
    return [pod for pod in env.items("pods") if metadata_labels(pod).get("app") == REDIS_HA]


def sentinel_pods(env: Environment) -> list[JsonObject]:
    """Return the pods of redis-ha's Sentinel StatefulSet; none while the chart renders no Sentinel."""
    return [pod for pod in env.items("pods") if metadata_name(pod).startswith(f"{SENTINEL}-")]


def redis_cli(env: Environment, pod: JsonObject, *args: str) -> str:
    """stdout of redis-cli with args against the pod's own Redis."""
    metadata = section(pod, "metadata")
    command = f"{REDIS_CLI} {shlex.join(args)}"
    return env.kube.run(
        "exec",
        f"pod/{metadata_name(pod)}",
        "-c",
        REDIS_HA,
        "--",
        "sh",
        "-c",
        command,
        namespace=str(metadata.get("namespace")),
    )


def reported_role(env: Environment, pod: JsonObject) -> str:
    """Return the role (master or slave) the pod's Redis reports in INFO replication."""
    found = re.search(r"^role:(\w+)", redis_cli(env, pod, "INFO", "replication"), re.MULTILINE)
    return found.group(1) if found else ""


def is_master_role_checked(pod: JsonObject) -> bool:
    """Return whether a master-labelled pod reporting role:slave goes NotReady (masterReadinessCheck)."""
    containers = entries(section(pod, "spec").get("containers"))
    probes = [section(container, "readinessProbe") for container in containers if container.get("name") == REDIS_HA]
    return any("role:" in str(section(probe, "exec").get("command")) for probe in probes)


def master_pod(env: Environment, replaced_uid: str | None = None) -> JsonObject | None:
    """Return the one pod behind redis-ha-master if its Redis reports role:master, else None.

    With replaced_uid, None also while that pod (by uid: a recreated pod keeps its name) is still behind it.
    """
    behind = ready_endpoints(env, MASTER_SERVICE)
    pods = {metadata_name(pod): pod for pod in redis_pods(env)}
    if len(behind) != 1 or behind[0] not in pods:
        return None
    pod = pods[behind[0]]
    if replaced_uid and section(pod, "metadata").get("uid") == replaced_uid:
        return None
    return pod if reported_role(env, pod) == "master" else None


def restart_master(env: Environment, master: JsonObject, timeout: float) -> None:
    """Delete the master pod, then wait until its replacement is ready and serves as master."""
    replace_pod(env, master, timeout)
    uid = str(section(master, "metadata").get("uid"))
    wait_until(lambda: master_pod(env, uid), timeout=timeout, description="a new Redis master")


@dataclass(frozen=True)
class Takeover:
    """The master after a failover, the seconds until redis-ha-master pointed at it, and what was wrong meanwhile."""

    master: JsonObject
    seconds: float
    problems: list[str]


def master_problem(env: Environment) -> str | None:
    """Describe redis-ha-master with several ready endpoints, or one whose Redis reports another role; else None."""
    behind = ready_endpoints(env, MASTER_SERVICE)
    if len(behind) > 1:
        return f"{MASTER_SERVICE} has {len(behind)} ready endpoints: {', '.join(behind)}"
    pods = {metadata_name(pod): pod for pod in redis_pods(env)}
    for name in behind:
        role = "master"
        with suppress(KubeError):  # the pod is going
            role = reported_role(env, pods[name]) if name in pods else role
        if role != "master":
            return f"{MASTER_SERVICE} points at {name}, which reports role:{role}"
    return None


def wait_for_takeover(env: Environment, replaced_uid: str, timeout: float) -> Takeover:
    """Wait for a master behind redis-ha-master other than the replaced pod, checking master_problem every second."""
    problems: list[str] = []
    start = time.monotonic()

    def probe() -> JsonObject | None:
        problem = master_problem(env)
        if problem:
            problems.append(problem)
        return master_pod(env, replaced_uid)

    master = wait_until(
        probe, timeout=timeout, interval=1, description=f"a master behind {MASTER_SERVICE} other than the deleted pod"
    )
    return Takeover(master, round(time.monotonic() - start, 1), list(dict.fromkeys(problems)))


def app_connections(env: Environment, pod: JsonObject) -> list[str]:
    """Return the address of each client of the pod's Redis that is no replication link and not the pod itself."""
    own = {str(section(pod, "status").get("podIP")), "127.0.0.1", "[::1]"}
    found: list[str] = []
    for line in redis_cli(env, pod, "CLIENT", "LIST").splitlines():
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        address = fields.get("addr", "")
        is_link = bool({"M", "S"} & set(fields.get("flags", "")))
        if address and not is_link and address.rsplit(":", 1)[0] not in own:
            found.append(address)
    return found


def replica_app_connections(env: Environment) -> dict[str, list[str]]:
    """Return the app connections of each redis-ha pod that reports role:slave, for the pods that have any."""
    replicas = [pod for pod in redis_pods(env) if reported_role(env, pod) == "slave"]
    connected = {metadata_name(pod): app_connections(env, pod) for pod in replicas}
    return {name: clients for name, clients in connected.items() if clients}
