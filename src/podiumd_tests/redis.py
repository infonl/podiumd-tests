"""Redis HA of the podiumd chart (redis-operator): its pods, the role each reports, and the Deployments using it."""

from __future__ import annotations

import re
import shlex

from contextlib import suppress
from typing import TYPE_CHECKING

from podiumd_tests.components import COMPONENTS
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_labels
from podiumd_tests.kube import metadata_name
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import pod_containers
from podiumd_tests.workloads import replace_pod

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
# REDISCLI_AUTH is the pods' own password variable, set only when Redis has one.
REDIS_CLI = "redis-cli -h $(hostname) -p ${REDIS_PORT:-6379}"


def _config_maps(deployment: JsonObject) -> set[str]:
    """Return the ConfigMaps the deployment's containers read variables from."""
    found: set[str] = set()
    for container in pod_containers(deployment, with_init=True):
        whole = [section(ref, "configMapRef") for ref in entries(container.get("envFrom"))]
        values = [section(variable, "valueFrom") for variable in entries(container.get("env"))]
        keys = [section(value, "configMapKeyRef") for value in values]
        found |= {str(ref.get("name")) for ref in (*whole, *keys) if ref}
    return found


def redis_deployments(env: Environment) -> list[str]:
    """Return the Deployments that read MASTER_SERVICE from a ConfigMap (CACHE_*, CELERY_BROKER_URL)."""
    data = {metadata_name(item): section(item, "data") for item in env.kube.items("configmaps")}

    def is_redis_user(deployment: JsonObject) -> bool:
        values = (value for name in _config_maps(deployment) for value in data.get(name, {}).values())
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


def ready_endpoints(env: Environment, service: str) -> list[str]:
    """Return the names of the pods behind the Service's ready endpoint addresses."""
    found = [endpoint for endpoint in env.items("endpoints") if metadata_name(endpoint) == service]
    subsets = [subset for endpoint in found for subset in entries(endpoint.get("subsets"))]
    return [
        str(section(address, "targetRef").get("name"))
        for subset in subsets
        for address in entries(subset.get("addresses"))
    ]


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
