"""Deployment hygiene of a workload: Pod Security Standard "baseline", pinned images, requests, disruption budgets.

Only the baseline level: most of PodiumD's charts do not meet "restricted" (allowPrivilegeEscalation,
seccompProfile), and estates may leave out memory limits on purpose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.kube import metadata_name
from podiumd_tests.kube import metadata_namespace
from podiumd_tests.workloads import pod_containers

if TYPE_CHECKING:
    from collections.abc import Sequence

    from podiumd_tests.json_data import JsonObject

# Capabilities the baseline level allows a container to add.
BASELINE_CAPABILITIES = frozenset(
    (
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
    )
)
# A disruption budget needs a second replica.
BUDGET_MIN_REPLICAS = 2


def baseline_violations(workload: JsonObject) -> list[str]:
    """Return what in the workload's pod template breaks the Pod Security Standard "baseline"."""
    name, pod = metadata_name(workload), section(section(section(workload, "spec"), "template"), "spec")
    found = [f"{name}: {key}" for key in ("hostNetwork", "hostPID", "hostIPC") if pod.get(key) is True]
    found += [
        f"{name}: hostPath volume {volume.get('name')}"
        for volume in entries(pod.get("volumes"))
        if "hostPath" in volume
    ]
    for container in pod_containers(workload, with_init=True):
        where = f"{name}/{container.get('name')}"
        context = section(container, "securityContext")
        if context.get("privileged") is True:
            found.append(f"{where}: privileged")
        added = set(strings(section(context, "capabilities").get("add"))) - BASELINE_CAPABILITIES
        if added:
            found.append(f"{where}: adds capabilities {sorted(added)}")
        found += [
            f"{where}: hostPort {port.get('hostPort')}"
            for port in entries(container.get("ports"))
            if port.get("hostPort")
        ]
    return found


def unpinned_images(workload: JsonObject) -> list[str]:
    """Images of the workload without a tag or digest, or tagged latest."""
    found: list[str] = []
    for container in pod_containers(workload, with_init=True):
        image = str(container.get("image") or "")
        if _is_unpinned(image):
            found.append(f"{metadata_name(workload)}/{container.get('name')}: {image}")
    return found


def _is_unpinned(image: str) -> bool:
    reference = image.rsplit("/", 1)[-1]
    return "@sha256:" not in image and (":" not in reference or reference.endswith(":latest"))


def missing_requests(workload: JsonObject) -> list[str]:
    """Containers of the workload without a CPU or a memory request: the scheduler cannot place them by size."""
    found: list[str] = []
    for container in pod_containers(workload, with_init=False):
        asked = section(section(container, "resources"), "requests")
        missing = [resource for resource in ("cpu", "memory") if not asked.get(resource)]
        if missing:
            found.append(f"{metadata_name(workload)}/{container.get('name')}: no {' or '.join(missing)} request")
    return found


def without_disruption_budget(workloads: Sequence[JsonObject], budgets: Sequence[JsonObject]) -> list[str]:
    """Names of the workloads with more than one replica whose pods no PodDisruptionBudget selects.

    A budget selects by its matchLabels only; matchExpressions are not evaluated.
    """
    replicated = [workload for workload in workloads if _is_replicated(workload)]
    return [metadata_name(workload) for workload in replicated if not _is_budgeted(workload, budgets)]


def _is_replicated(workload: JsonObject) -> bool:
    replicas = section(workload, "spec").get("replicas", 1)
    return isinstance(replicas, int) and replicas >= BUDGET_MIN_REPLICAS


def _is_budgeted(workload: JsonObject, budgets: Sequence[JsonObject]) -> bool:
    """Whether a PodDisruptionBudget in the workload's namespace selects its pods."""
    labels = section(section(section(section(workload, "spec"), "template"), "metadata"), "labels")
    return any(
        metadata_namespace(budget) == metadata_namespace(workload)
        and section(section(section(budget, "spec"), "selector"), "matchLabels").items() <= labels.items()
        for budget in budgets
    )
