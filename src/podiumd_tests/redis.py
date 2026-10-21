"""Redis HA of the podiumd chart (redis-operator): the replication role each pod reports."""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

# The redis-operator's StatefulSet, Services and container of the podiumd chart.
REDIS_HA = "redis-ha"
MASTER_SERVICE = "redis-ha-master"
# The operator labels the pod it made master; redis-ha-master selects that label.
MASTER_LABEL = "redis-role"
# REDISCLI_AUTH is the pods' own password variable, set only when Redis has one.
INFO_REPLICATION = "redis-cli -h $(hostname) -p ${REDIS_PORT:-6379} INFO replication"


def redis_pods(env: Environment) -> list[JsonObject]:
    """The pods of the redis-ha StatefulSet."""
    return [p for p in env.items("pods") if section(section(p, "metadata"), "labels").get("app") == REDIS_HA]


def reported_role(env: Environment, pod: JsonObject) -> str:
    """The role (master or slave) the pod's Redis reports in INFO replication."""
    metadata = section(pod, "metadata")
    out = env.kube.run(
        "exec",
        f"pod/{metadata_name(pod)}",
        "-c",
        REDIS_HA,
        "--",
        "sh",
        "-c",
        INFO_REPLICATION,
        namespace=str(metadata.get("namespace")),
    )
    found = re.search(r"^role:(\w+)", out, re.MULTILINE)
    return found.group(1) if found else ""


def checks_master_role(pod: JsonObject) -> bool:
    """The pod's readiness probe makes a master-labelled pod that reports role:slave NotReady (masterReadinessCheck)."""
    containers = entries(section(pod, "spec").get("containers"))
    probes = [section(c, "readinessProbe") for c in containers if c.get("name") == REDIS_HA]
    return any("role:" in str(section(p, "exec").get("command")) for p in probes)


def ready_endpoints(env: Environment, service: str) -> list[str]:
    """The names of the pods behind the Service's ready endpoint addresses."""
    found = [e for e in env.items("endpoints") if metadata_name(e) == service]
    return [
        str(section(a, "targetRef").get("name"))
        for e in found
        for subset in entries(e.get("subsets"))
        for a in entries(subset.get("addresses"))
    ]
