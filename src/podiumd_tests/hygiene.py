"""Deployment hygiene of a workload: Kubernetes' Pod Security Standard "baseline", pinned images, resource requests.

Only the baseline level: most of PodiumD's charts do not meet "restricted" (allowPrivilegeEscalation,
seccompProfile), and estates may leave out memory limits on purpose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.kube import metadata_name
from podiumd_tests.workloads import pod_containers

if TYPE_CHECKING:
    from podiumd_tests.json_data import JsonObject

# Capabilities the baseline level allows a container to add.
BASELINE_CAPABILITIES = frozenset(
    {
        "AUDIT_WRITE",
        "CHOWN",
        "DAC_OVERRIDE",
        "FOWNER",
        "FSETID",
        "KILL",
        "MKNOD",
        "NET_BIND_SERVICE",
        "SETFCAP",
        "SETGID",
        "SETPCAP",
        "SETUID",
        "SYS_CHROOT",
    }
)


def baseline_violations(workload: JsonObject) -> list[str]:
    """What in the workload's pod template breaks the Pod Security Standard "baseline"."""
    name, pod = metadata_name(workload), section(section(section(workload, "spec"), "template"), "spec")
    found = [f"{name}: {key}" for key in ("hostNetwork", "hostPID", "hostIPC") if pod.get(key) is True]
    found += [f"{name}: hostPath volume {v.get('name')}" for v in entries(pod.get("volumes")) if "hostPath" in v]
    for container in pod_containers(workload, with_init=True):
        where = f"{name}/{container.get('name')}"
        context = section(container, "securityContext")
        if context.get("privileged") is True:
            found.append(f"{where}: privileged")
        added = set(strings(section(context, "capabilities").get("add"))) - BASELINE_CAPABILITIES
        if added:
            found.append(f"{where}: adds capabilities {sorted(added)}")
        found += [
            f"{where}: hostPort {p.get('hostPort')}" for p in entries(container.get("ports")) if p.get("hostPort")
        ]
    return found


def unpinned_images(workload: JsonObject) -> list[str]:
    """Images of the workload without a tag or digest, or tagged latest."""
    found: list[str] = []
    for container in pod_containers(workload, with_init=True):
        image = str(container.get("image") or "")
        reference = image.rsplit("/", 1)[-1]
        if "@sha256:" not in image and (":" not in reference or reference.endswith(":latest")):
            found.append(f"{metadata_name(workload)}/{container.get('name')}: {image}")
    return found


def missing_requests(workload: JsonObject) -> list[str]:
    """Containers of the workload without a CPU or a memory request: the scheduler cannot place them by size."""
    found: list[str] = []
    for container in pod_containers(workload, with_init=False):
        asked = section(section(container, "resources"), "requests")
        missing = [r for r in ("cpu", "memory") if not asked.get(r)]
        if missing:
            found.append(f"{metadata_name(workload)}/{container.get('name')}: no {' or '.join(missing)} request")
    return found
