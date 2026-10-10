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
from podiumd_tests.responses import root_answers
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Generator
    from collections.abc import Sequence

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.kube import Kube

type Item = JsonObject

GOOD_POD_PHASES = frozenset({"Running", "Succeeded"})
# Seconds a stopped or restarted component's root gets to answer.
ROOT_TIMEOUT = 10.0


def pod_containers(workload: JsonObject, *, with_init: bool) -> list[JsonObject]:
    """The containers of a Deployment's or StatefulSet's pod template, init containers first when asked."""
    pod = section(section(section(workload, "spec"), "template"), "spec")
    found = entries(pod.get("containers"))
    return [*entries(pod.get("initContainers")), *found] if with_init else found


def _owner_kinds(item: Item) -> set[str]:
    return {str(o.get("kind")) for o in entries(section(item, "metadata").get("ownerReferences"))}


def _owner_name(item: Item, kind: str) -> str | None:
    owners = entries(section(item, "metadata").get("ownerReferences"))
    return next((str(o.get("name")) for o in owners if o.get("kind") == kind), None)


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


@contextmanager
def scaled(kube: Kube, deployment: str, replicas: int, timeout: int = 300) -> Generator[None]:
    """Run the block with the deployment at `replicas`; afterwards restore its replicas. Both wait for the rollout."""
    before = _int(section(kube.get_json("deployment", deployment), "spec").get("replicas"))

    def scale(count: int) -> None:
        kube.run("scale", f"deployment/{deployment}", f"--replicas={count}")
        kube.run("rollout", "status", f"deployment/{deployment}", f"--timeout={timeout}s", timeout=timeout + 10)

    scale(replicas)
    try:
        yield
    finally:
        scale(before)


def run_cronjob(kube: Kube, cronjob: str, job: str, timeout: int = 300) -> None:
    """Run the CronJob once now, as Job `job`; returns when it completed and deletes the Job either way."""
    kube.run("create", "job", job, f"--from=cronjob/{cronjob}")
    try:
        kube.run("wait", "--for=condition=complete", f"job/{job}", f"--timeout={timeout}s", timeout=timeout + 10)
    finally:
        kube.delete("job", job)


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


@contextmanager
def component_down(env: Environment, http: requests.Session, component: str) -> Generator[None]:
    """Run the block with the component's main deployment stopped and its root failing.

    Afterwards the deployment is restored and the block returns once the root answers again.
    """
    url = env.profile.urls[component]
    with scaled(env.kube, env.deployment_for(component), 0):
        wait_until(lambda: not root_answers(http, url, ROOT_TIMEOUT), timeout=120, description=f"{component} stopped")
        yield
    wait_until(lambda: root_answers(http, url, ROOT_TIMEOUT), timeout=300, description=f"{component} answers again")
