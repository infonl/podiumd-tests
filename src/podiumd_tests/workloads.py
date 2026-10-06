"""Health of the Kubernetes workloads, judged from `kubectl get -o json` items.

Ported from podiumd-minikube and podiumd-infra tests/test_pods.py. Instead of
a list of one-shot Job name prefixes (which differs per chart version and
estate), pods are judged by their owner: pods of a Job count through the Job,
and only the latest Job of each CronJob counts, as older runs are history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.kube import metadata_name

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

type Item = Mapping[str, object]

GOOD_POD_PHASES = frozenset({"Running", "Succeeded"})


def _section(item: Item, key: str) -> Item:
    value = item.get(key)
    return cast("Item", value) if isinstance(value, dict) else {}


def _entries(value: object) -> list[Item]:
    """The objects in a JSON list; anything else gives an empty list."""
    if not isinstance(value, list):
        return []
    return [cast("Item", e) for e in cast("list[object]", value) if isinstance(e, dict)]


def _owner_kinds(item: Item) -> set[str]:
    return {str(o.get("kind")) for o in _entries(_section(item, "metadata").get("ownerReferences"))}


def _owner_name(item: Item, kind: str) -> str | None:
    owners = _entries(_section(item, "metadata").get("ownerReferences"))
    return next((str(o.get("name")) for o in owners if o.get("kind") == kind), None)


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def unready_workloads(items: Sequence[Item]) -> list[str]:
    """Deployments and StatefulSets with fewer ready replicas than wanted, as "name ready/wanted"."""
    found: list[str] = []
    for item in items:
        replicas = _section(item, "spec").get("replicas", 1)
        wanted = replicas if isinstance(replicas, int) else 1
        ready = _int(_section(item, "status").get("readyReplicas"))
        if ready < wanted:
            found.append(f"{item.get('kind', '?')}/{metadata_name(item)} {ready}/{wanted}")
    return found


def unhealthy_pods(pods: Sequence[Item]) -> list[str]:
    """Long-running pods that are not Running with all containers ready, as "name: reason".

    Pods of Jobs are left to failed_jobs; pods being deleted are ignored.
    """
    found: list[str] = []
    for pod in pods:
        if "Job" in _owner_kinds(pod) or _section(pod, "metadata").get("deletionTimestamp"):
            continue
        status = _section(pod, "status")
        phase = str(status.get("phase", "Unknown"))
        name = metadata_name(pod)
        if phase not in GOOD_POD_PHASES:
            found.append(f"{name}: phase {phase}")
            continue
        if phase == "Succeeded":
            continue
        containers = _entries(status.get("containerStatuses"))
        found.extend(f"{name}/{c.get('name', '?')}: not ready" for c in containers if not c.get("ready"))
    return found


def _job_failed(job: Item) -> bool:
    conditions = _entries(_section(job, "status").get("conditions"))
    return any(c.get("type") == "Failed" and c.get("status") == "True" for c in conditions)


def failed_jobs(jobs: Sequence[Item]) -> list[str]:
    """Jobs that failed: every standalone Job, and the latest Job of each CronJob."""
    latest: dict[str, Item] = {}
    standalone: list[Item] = []
    for job in jobs:
        cronjob = _owner_name(job, "CronJob")
        if cronjob is None:
            standalone.append(job)
            continue
        created = str(_section(job, "metadata").get("creationTimestamp", ""))
        current = latest.get(cronjob)
        if current is None or created > str(_section(current, "metadata").get("creationTimestamp", "")):
            latest[cronjob] = job
    return sorted(metadata_name(j) for j in [*standalone, *latest.values()] if _job_failed(j))
