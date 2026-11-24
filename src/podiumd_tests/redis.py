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
from podiumd_tests.process import start_process
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import ready_endpoints
from podiumd_tests.workloads import replace_pod
from podiumd_tests.workloads import variable_config_maps

if TYPE_CHECKING:
    import subprocess  # nosec B404  # type only

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
# The operator labels redis-ha's Redis pods role=replication and, with Sentinel on (helm-charts #754), its Sentinel
# pods role=sentinel; both carry app=redis-ha.
SENTINEL_ROLE = "sentinel"
# The Deployment that labels the master Sentinel elected and fences the old one (helm-charts #754).
LABELLER = "redis-ha-labeller"
# A replica takes over within this many seconds of the master pod or its node going (podiumd-chart-24).
TAKEOVER_SECONDS = 30
# Seconds the writer writes through redis-ha-master: longer than a takeover; its writes come every 0.2 s.
WRITE_SECONDS = 60
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


def _redis_ha_pods(env: Environment, *, sentinels: bool) -> list[JsonObject]:
    """Return redis-ha's Sentinel pods, or its Redis pods."""
    found: list[JsonObject] = []
    for pod in env.items("pods"):
        labels = metadata_labels(pod)
        if labels.get("app") == REDIS_HA and (labels.get("role") == SENTINEL_ROLE) == sentinels:
            found.append(pod)
    return found


def redis_pods(env: Environment) -> list[JsonObject]:
    """Return the Redis pods of redis-ha, without its Sentinel pods."""
    return _redis_ha_pods(env, sentinels=False)


def sentinel_pods(env: Environment) -> list[JsonObject]:
    """Return redis-ha's Sentinel pods; none while the chart renders no Sentinel."""
    return _redis_ha_pods(env, sentinels=True)


def labeller_pods(env: Environment) -> list[JsonObject]:
    """Return the pods of LABELLER; none while the chart renders no Sentinel."""
    return [pod for pod in env.items("pods") if metadata_labels(pod).get("app.kubernetes.io/name") == LABELLER]


def placement(env: Environment) -> dict[str, str]:
    """Return the node of each Redis, Sentinel and labeller pod of redis-ha."""
    pods = [*redis_pods(env), *sentinel_pods(env), *labeller_pods(env)]
    return {metadata_name(pod): str(section(pod, "spec").get("nodeName")) for pod in pods}


def labeller_logs(env: Environment, since_time: str) -> dict[str, str]:
    """Return what each labeller pod logged since the RFC 3339 time since_time."""
    logs: dict[str, str] = {}
    for pod in labeller_pods(env):
        namespace = str(section(pod, "metadata").get("namespace"))
        logs[metadata_name(pod)] = env.kube.run(
            "logs", f"pod/{metadata_name(pod)}", f"--since-time={since_time}", namespace=namespace
        )
    return logs


def master_changes(log: str) -> list[str]:
    """Return the pod of each "master change" line of a labeller log, in order."""
    return re.findall(r"master change: (\S+) is master", log)


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
    """Return the address of each client of the pod's Redis that is no replication link, Sentinel or the pod itself."""
    own = {str(section(pod, "status").get("podIP")), "127.0.0.1", "[::1]"}
    found: list[str] = []
    for line in redis_cli(env, pod, "CLIENT", "LIST").splitlines():
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        address = fields.get("addr", "")
        is_sentinel = fields.get("name", "").startswith("sentinel-")
        is_link = is_sentinel or bool({"M", "S"} & set(fields.get("flags", "")))
        if address and not is_link and address.rsplit(":", 1)[0] not in own:
            found.append(address)
    return found


def replica_app_connections(env: Environment) -> dict[str, list[str]]:
    """Return the app connections of each redis-ha pod that reports role:slave, for the pods that have any."""
    replicas = [pod for pod in redis_pods(env) if reported_role(env, pod) == "slave"]
    connected = {metadata_name(pod): app_connections(env, pod) for pod in replicas}
    return {name: clients for name, clients in connected.items() if clients}


# Run in a Redis pod (the NetworkPolicy admits redis-ha's own pods): SET <prefix><n> <n> through redis-ha-master,
# one line "<n> <reply>" per write.
_WRITER = """
end=$(( $(date +%s) + $1 )); n=0
while [ "$(date +%s)" -lt "$end" ]; do
  n=$((n + 1))
  echo "$n $(timeout 2 redis-cli -h redis-ha-master -p "${REDIS_PORT:-6379}" SET "$2$n" "$n" 2>&1)"
  sleep 0.2
done
"""


def start_writer(env: Environment, pod: JsonObject, prefix: str) -> subprocess.Popen[str]:
    """Start writing <prefix><n> through redis-ha-master from the pod for WRITE_SECONDS; it stops by itself."""
    namespace = str(section(pod, "metadata").get("namespace"))
    command = env.kube.command(
        "exec",
        f"pod/{metadata_name(pod)}",
        "-c",
        REDIS_HA,
        "--",
        "sh",
        "-c",
        _WRITER,
        "writer",
        str(WRITE_SECONDS),
        prefix,
        namespace=namespace,
    )
    return start_process(command)


def acknowledged_writes(writer: subprocess.Popen[str]) -> list[int]:
    """Wait for the writer to end; return the numbers of the writes Redis answered OK."""
    out, _ = writer.communicate(timeout=WRITE_SECONDS + 60)
    found = (re.fullmatch(r"(\d+) OK", line) for line in out.splitlines())
    return [int(match.group(1)) for match in found if match]


def missing_writes(env: Environment, master: JsonObject, prefix: str, numbers: list[int]) -> list[int]:
    """Return the numbers whose key <prefix><n> the master does not hold with value n."""
    if not numbers:
        return []
    values = redis_cli(env, master, "MGET", *(f"{prefix}{number}" for number in numbers)).splitlines()
    held = dict(zip(numbers, values, strict=False))
    return [number for number in numbers if held.get(number, "").strip() != str(number)]


def delete_writes(env: Environment, master: JsonObject, prefix: str) -> None:
    """Delete every key the writer can have written (at most 5 per second)."""
    numbers = range(1, WRITE_SECONDS * 5 + 2)
    redis_cli(env, master, "DEL", *(f"{prefix}{number}" for number in numbers))


def replication_state(env: Environment) -> dict[str, str]:
    """Return each Redis pod's role, master host, link status and replication offset, from INFO replication."""
    wanted = ("role", "master_host", "master_link_status", "master_repl_offset", "connected_slaves")
    state: dict[str, str] = {}
    for pod in redis_pods(env):
        lines = redis_cli(env, pod, "INFO", "replication").splitlines()
        info = dict(line.split(":", 1) for line in lines if ":" in line)
        pairs = [f"{key}={info[key].strip()}" for key in wanted if key in info]
        state[metadata_name(pod)] = " ".join(pairs)
    return state
