"""Health of the Kubernetes workloads, judged from `kubectl get -o json` items.

Ported from podiumd-minikube and podiumd-infra tests/test_pods.py. Instead of
a list of one-shot Job name prefixes (which differs per chart version and
estate), pods are judged by their owner: pods of a Job count through the Job,
and only the latest Job of each CronJob counts, as older runs are history.
"""

from __future__ import annotations

import contextlib
import re

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from podiumd_tests.json_data import JsonObject
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_name
from podiumd_tests.responses import root_answers
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Generator
    from collections.abc import Mapping
    from collections.abc import Sequence

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.kube import Kube

type Item = JsonObject

GOOD_POD_PHASES = frozenset({"Running", "Succeeded"})
# app labels of workloads that are no part of PodiumD. deploy-warmup: podiumd-infra's node pre-scale
# placeholder during a deploy (scripts/prescale-warmup.sh), whose pause pods are meant to stay Pending.
FOREIGN_APPS = frozenset({"deploy-warmup"})
# Seconds a stopped or restarted component's root gets to answer.
ROOT_TIMEOUT = 10.0


def pod_containers(workload: JsonObject, *, with_init: bool) -> list[JsonObject]:
    """The containers of a Deployment's or StatefulSet's pod template, init containers first when asked."""
    pod = section(section(section(workload, "spec"), "template"), "spec")
    found = entries(pod.get("containers"))
    return [*entries(pod.get("initContainers")), *found] if with_init else found


def readiness_window(workload: JsonObject) -> int:
    """Most seconds of failing readiness probes before a pod of the workload leaves its Service.

    Unset probe fields take the Kubernetes defaults.
    """
    windows = [0]
    for container in pod_containers(workload, with_init=False):
        probe = section(container, "readinessProbe")
        if probe:
            failures = probe.get("failureThreshold", 3)
            period = probe.get("periodSeconds", 10)
            timeout = probe.get("timeoutSeconds", 1)
            windows.append(_int(failures) * (_int(period) + _int(timeout)))
    return max(windows)


def _main_deployment(env: Environment, deployments: Mapping[str, Item], component: str) -> Item | None:
    try:
        return deployments[env.deployment_for(component)]
    except KubeError:  # the component has no main deployment
        return None


def component_versions(env: Environment, components: Sequence[str]) -> dict[str, tuple[int, ...]]:
    """Versions of the components' main deployments, e.g. {"ita": (3, 3, 4)}; unknown ones are left out.

    The numeric image tag; for an image pinned by digest only (podiumd-infra), the image's own
    RELEASE variable (Maykin images set it); else Helm's app.kubernetes.io/version label, which
    is the sub-chart's appVersion and can lag behind the image.
    """
    deployments = {metadata_name(d): d for d in env.items("deployments")}
    found: dict[str, tuple[int, ...]] = {}
    for component in components:
        workload = _main_deployment(env, deployments, component)
        if workload is None:
            continue
        version = image_version(workload)
        if version is None:
            label = str(section(section(workload, "metadata"), "labels").get("app.kubernetes.io/version", ""))
            version = _version(_image_release(env, metadata_name(workload))) or _version(label)
        if version:
            found[component] = version
    return found


def image_version(workload: JsonObject) -> tuple[int, ...] | None:
    """The first version image tag of the workload's containers: "repo:v0.27.0@sha256:..." -> (0, 27, 0)."""
    for container in pod_containers(workload, with_init=False):
        name = str(container.get("image")).partition("@")[0]
        # "repo@sha256:..." has no tag; a ":" before the last "/" is a registry port.
        tag = name.rpartition(":")[2] if ":" in name.rpartition("/")[2] else ""
        version = _version(tag.removeprefix("v"))
        if version:
            return version
    return None


def _version(value: str) -> tuple[int, ...] | None:
    return tuple(int(n) for n in value.split(".")) if re.fullmatch(r"\d+(\.\d+)+", value) else None


def _image_release(env: Environment, deployment: str) -> str:
    """The RELEASE variable of a deployment's image, or "" when the pod cannot tell."""
    try:
        return env.kube.exec(deployment, "printenv", "RELEASE", timeout=30).strip()
    except KubeError:
        return ""


def chart_version(env: Environment) -> str | None:
    """The podiumd chart's version: Helm's app.kubernetes.io/version label on podiumd's own ConfigMaps."""
    for config_map in env.items("configmaps"):
        labels = section(section(config_map, "metadata"), "labels")
        if labels.get("app.kubernetes.io/name") == "podiumd" and labels.get("app.kubernetes.io/version"):
            return str(labels["app.kubernetes.io/version"])
    return None


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
    except KubeError as error:
        error.add_note(_job_log(kube, job))
        raise
    finally:
        kube.delete("job", job)


def _job_log(kube: Kube, job: str) -> str:
    """The last lines a Job's container wrote; its previous run when it restarts."""
    for previous in ([], ["--previous"]):
        with contextlib.suppress(KubeError):
            if log := kube.run("logs", f"job/{job}", "--tail=60", *previous):
                return f"log of job/{job}:\n{log}"
    return f"no log of job/{job}"


def _foreign(item: Item) -> bool:
    return section(section(item, "metadata"), "labels").get("app") in FOREIGN_APPS


def unready_workloads(items: Sequence[Item]) -> list[str]:
    """Deployments and StatefulSets with fewer ready replicas than wanted, as "name ready/wanted"."""
    found: list[str] = []
    for item in items:
        if _foreign(item):
            continue
        replicas = section(item, "spec").get("replicas", 1)
        wanted = replicas if isinstance(replicas, int) else 1
        ready = _int(section(item, "status").get("readyReplicas"))
        if ready < wanted:
            found.append(f"{item.get('kind', '?')}/{metadata_name(item)} {ready}/{wanted}")
    return found


def unhealthy_pods(pods: Sequence[Item]) -> list[str]:
    """Long-running pods that are not Running with all containers ready, as "name: reason".

    Pods of Jobs are left to failed_jobs; pods being deleted and FOREIGN_APPS are ignored.
    """
    found: list[str] = []
    for pod in pods:
        if "Job" in _owner_kinds(pod) or section(pod, "metadata").get("deletionTimestamp") or _foreign(pod):
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


@dataclass(frozen=True)
class ClusterState:
    """The long-running pods of the environment by uid, and the cluster's nodes."""

    pods: dict[str, Item]
    nodes: frozenset[str]


def cluster_state(env: Environment) -> ClusterState:
    """The pods (not of Jobs) and nodes now, to compare with a later state."""
    pods = {
        str(section(p, "metadata").get("uid")): p for p in entries(env.items("pods")) if "Job" not in _owner_kinds(p)
    }
    return ClusterState(pods, frozenset(metadata_name(n) for n in env.kube.items("nodes")))


def disruptions(before: ClusterState, after: ClusterState) -> list[str]:
    """Nodes and pods that came or went between two states, and containers that restarted, one line each."""
    found = [f"node {n} removed" for n in sorted(before.nodes - after.nodes)]
    found += [f"node {n} added" for n in sorted(after.nodes - before.nodes)]
    found += [f"pod {_where(p)} gone" for uid, p in before.pods.items() if uid not in after.pods]
    found += [
        f"pod {_where(p)} started {section(p, 'metadata').get('creationTimestamp')}"
        for uid, p in after.pods.items()
        if uid not in before.pods
    ]
    for uid, pod in after.pods.items():
        earlier = {
            str(c.get("name")): c for c in entries(section(before.pods.get(uid, {}), "status").get("containerStatuses"))
        }
        for container in entries(section(pod, "status").get("containerStatuses")):
            name = str(container.get("name"))
            if name not in earlier:
                continue
            restarts = _int(container.get("restartCount")) - _int(earlier[name].get("restartCount"))
            if restarts > 0:
                last = section(section(container, "lastState"), "terminated")
                found.append(
                    f"container {metadata_name(pod)}/{name} restarted {restarts}x"
                    f" (last: {last.get('reason', '?')} at {last.get('finishedAt', '?')})"
                )
    return found


def _where(pod: Item) -> str:
    return f"{metadata_name(pod)} on {section(pod, 'spec').get('nodeName', '?')}"


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
