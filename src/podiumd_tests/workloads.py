"""Health of the Kubernetes workloads, judged from `kubectl get -o json` items.

Ported from podiumd-minikube and podiumd-infra tests/test_pods.py. Instead of
a list of one-shot Job name prefixes (which differs per chart version and
estate), pods are judged by their owner: pods of a Job count through the Job,
and only the latest Job of each CronJob counts, as older runs are history.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from podiumd_tests.json_data import JsonObject
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name

if TYPE_CHECKING:
    from collections.abc import Generator
    from collections.abc import Sequence

    from podiumd_tests.kube import Kube

type Item = JsonObject

GOOD_POD_PHASES = frozenset({"Running", "Succeeded"})


def _owner_kinds(item: Item) -> set[str]:
    return {str(o.get("kind")) for o in entries(section(item, "metadata").get("ownerReferences"))}


def _owner_name(item: Item, kind: str) -> str | None:
    owners = entries(section(item, "metadata").get("ownerReferences"))
    return next((str(o.get("name")) for o in owners if o.get("kind") == kind), None)


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


@contextmanager
def stopped(kube: Kube, deployment: str, timeout: int = 300) -> Generator[None]:
    """Scale the deployment to 0 for the block; afterwards restore its replicas and wait for the rollout."""
    replicas = _int(section(kube.get_json("deployment", deployment), "spec").get("replicas"))
    kube.run("scale", f"deployment/{deployment}", "--replicas=0")
    try:
        yield
    finally:
        kube.run("scale", f"deployment/{deployment}", f"--replicas={replicas}")
        kube.run("rollout", "status", f"deployment/{deployment}", f"--timeout={timeout}s", timeout=timeout + 10)


def unready_workloads(items: Sequence[Item]) -> list[str]:
    """Deployments and StatefulSets with fewer ready replicas than wanted, as "name ready/wanted"."""
    found: list[str] = []
    for item in items:
        replicas = section(item, "spec").get("replicas", 1)
        wanted = replicas if isinstance(replicas, int) else 1
        ready = _int(section(item, "status").get("readyReplicas"))
        if ready < wanted:
            found.append(f"{item.get('kind', '?')}/{metadata_name(item)} {ready}/{wanted}")
    return found


def unhealthy_pods(pods: Sequence[Item]) -> list[str]:
    """Long-running pods that are not Running with all containers ready, as "name: reason".

    Pods of Jobs are left to failed_jobs; pods being deleted are ignored.
    """
    found: list[str] = []
    for pod in pods:
        if "Job" in _owner_kinds(pod) or section(pod, "metadata").get("deletionTimestamp"):
            continue
        status = section(pod, "status")
        phase = str(status.get("phase", "Unknown"))
        name = metadata_name(pod)
        if phase not in GOOD_POD_PHASES:
            found.append(f"{name}: phase {phase}")
            continue
        if phase == "Succeeded":
            continue
        containers = entries(status.get("containerStatuses"))
        found.extend(f"{name}/{c.get('name', '?')}: not ready" for c in containers if not c.get("ready"))
    return found


def _job_failed(job: Item) -> bool:
    conditions = entries(section(job, "status").get("conditions"))
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
        created = str(section(job, "metadata").get("creationTimestamp", ""))
        current = latest.get(cronjob)
        if current is None or created > str(section(current, "metadata").get("creationTimestamp", "")):
            latest[cronjob] = job
    return sorted(metadata_name(j) for j in [*standalone, *latest.values()] if _job_failed(j))
