"""Health of the Kubernetes workloads, judged from `kubectl get -o json` items.

Ported from podiumd-minikube and podiumd-infra tests/test_pods.py. Instead of
a list of one-shot Job name prefixes (which differs per chart version and
estate), pods are judged by their owner: pods of a Job count through the Job,
and only the latest Job of each CronJob counts, as older runs are history.
"""

from __future__ import annotations

import base64
import gzip
import json
import re

from contextlib import contextmanager
from contextlib import suppress
from dataclasses import dataclass
from itertools import chain
from itertools import starmap
from typing import TYPE_CHECKING
from typing import NamedTuple
from typing import cast

import pytest
import yaml

from podiumd_tests.json_data import JsonObject
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import is_condition_true
from podiumd_tests.kube import metadata_labels
from podiumd_tests.kube import metadata_name
from podiumd_tests.kube import metadata_namespace
from podiumd_tests.responses import is_root_answering
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator
    from collections.abc import Mapping
    from collections.abc import Sequence

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.kube import Kube

type Item = JsonObject

GOOD_POD_PHASES = frozenset(("Running", "Succeeded"))
# app labels of workloads that are no part of PodiumD. deploy-warmup: podiumd-infra's node pre-scale
# placeholder during a deploy (scripts/prescale-warmup.sh), whose pause pods are meant to stay Pending.
FOREIGN_APPS = frozenset(("deploy-warmup",))
# Seconds a stopped or restarted component's root gets to answer.
ROOT_TIMEOUT = 10.0
# Longest deployed_build entry shown; podiumd-minikube's object map `charts` is longer.
BUILD_ENTRY_LIMIT = 200


def pod_containers(workload: JsonObject, *, with_init: bool) -> list[JsonObject]:
    """Return the containers of a Deployment's or StatefulSet's pod template, init containers first when asked."""
    pod = section(section(section(workload, "spec"), "template"), "spec")
    found = entries(pod.get("containers"))
    return [*entries(pod.get("initContainers")), *found] if with_init else found


def _main_deployment(env: Environment, deployments: Mapping[str, Item], component: str) -> Item | None:
    try:
        return deployments[env.deployment_for(component)]
    except KubeError:  # the component has no main deployment
        return None


def component_versions(env: Environment, components: Sequence[str]) -> dict[str, tuple[int, ...]]:
    """Versions of the components' main deployments, e.g. {"ita": (3, 3, 4)}; unknown ones are left out.

    The numeric image tag; for an image pinned by digest only (podiumd-infra), the version the image itself
    states (_image_release); else Helm's app.kubernetes.io/version label, which is the sub-chart's appVersion
    and can lag behind the image.
    """
    deployments = {metadata_name(deployment): deployment for deployment in env.items("deployments")}
    found: dict[str, tuple[int, ...]] = {}
    for component in components:
        workload = _main_deployment(env, deployments, component)
        if workload is None:
            continue
        version = image_version(workload)
        if version is None:
            label = str(metadata_labels(workload).get("app.kubernetes.io/version", ""))
            version = _version(_image_release(env, component, metadata_name(workload))) or _version(label)
        if version:
            found[component] = version
    return found


def image_version(workload: JsonObject) -> tuple[int, ...] | None:
    """Return the first version image tag of the workload's containers: "repo:v0.27.0@sha256:..." -> (0, 27, 0)."""
    for container in pod_containers(workload, with_init=False):
        name = str(container.get("image")).partition("@")[0]
        # "repo@sha256:..." has no tag; a ":" before the last "/" is a registry port.
        tag = name.rpartition(":")[2] if ":" in name.rpartition("/")[2] else ""
        version = _version(tag.removeprefix("v"))
        if version:
            return version
    return None


def _version(value: str) -> tuple[int, ...] | None:
    if not re.fullmatch(r"\d+(\.\d+)+", value):
        return None
    return tuple(int(part) for part in value.split("."))


# Images without a version variable: the Python package whose __version__ ("v2.4.9") states it.
VERSION_PACKAGES = {"openinwoner": ("/app/src", "open_inwoner")}


def _image_release(env: Environment, component: str, deployment: str) -> str:
    """Return the version a deployment's image states, or "" when the pod cannot tell.

    Maykin images set RELEASE, ZAC sets VERSION_NUMBER; Open Inwoner sets RELEASE empty.
    """
    variables = 'echo "${RELEASE:-$VERSION_NUMBER}"'
    try:
        found = env.kube.exec(deployment, "sh", "-c", variables, timeout=30).strip()
    except KubeError:
        found = ""
    if found:
        return found
    if component not in VERSION_PACKAGES:
        return ""
    path, package = VERSION_PACKAGES[component]
    code = f"import sys; sys.path.insert(0, {path!r}); import {package}; print({package}.__version__)"
    try:
        printed = env.kube.exec(deployment, "python", "-c", code, timeout=60)
    except KubeError:
        return ""
    lines = printed.strip().splitlines()
    return lines[-1].removeprefix("v") if lines else ""


def chart_version(env: Environment) -> str | None:
    """Return the podiumd chart's version: Helm's app.kubernetes.io/version label on podiumd's own ConfigMaps.

    None when no ConfigMap has it or the cluster is unreachable.
    """
    try:
        config_maps = env.items("configmaps")
    except KubeError:
        return None
    for config_map in config_maps:
        labels = metadata_labels(config_map)
        if labels.get("app.kubernetes.io/name") == "podiumd" and labels.get("app.kubernetes.io/version"):
            return str(labels["app.kubernetes.io/version"])
    return None


def deployed_build(env: Environment) -> dict[str, str]:
    """Return the one-line entries of the ConfigMap setting deployed_build names ("namespace/name"); {} when unreadable.

    The deployer records there what the chart version hides, such as a local chart checkout. Entries over
    BUILD_ENTRY_LIMIT characters are left out.
    """
    namespace, _, name = env.profile.settings.get("deployed_build", "").partition("/")
    if not name:
        return {}
    try:
        data = section(env.kube.get_json("configmap", name, namespace=namespace), "data")
    except KubeError:
        return {}
    texts = {key: str(value) for key, value in data.items()}
    short = {key: text for key, text in texts.items() if len(text) <= BUILD_ENTRY_LIMIT}
    return {key: text for key, text in short.items() if "\n" not in text}


def expect_defect(  # noqa: PLR0913  # one marker
    request: pytest.FixtureRequest,
    env: Environment,
    component: str,
    affected: Callable[[tuple[int, ...]], bool],
    *,
    raises: type[BaseException],
    reason: str,
) -> None:
    """Mark the test a strict xfail when the deployed component's version is affected; an unknown version is not."""
    version = component_versions(env, [component]).get(component)
    if version is not None and affected(version):
        request.applymarker(pytest.mark.xfail(strict=True, raises=raises, reason=reason))


def skip_older_than(env: Environment, component: str, version: tuple[int, ...], behaviour: str) -> None:
    """Skip the test when the deployed component is older than `version`; an unknown version runs it."""
    found = component_versions(env, [component]).get(component)
    if found is not None and found < version:
        shown = ".".join(map(str, found))
        pytest.skip(f"{component} {shown} is older than {'.'.join(map(str, version))}: {behaviour}")


def is_chart_older_than(env: Environment, version: tuple[int, ...]) -> bool:
    """Whether the deployed podiumd chart is older than `version`; True when its version is unknown."""
    found = _version(chart_version(env) or "")
    return found is None or found < version


def _owner_kinds(item: Item) -> set[str]:
    return {str(owner.get("kind")) for owner in entries(section(item, "metadata").get("ownerReferences"))}


def _owner_name(item: Item, kind: str) -> str | None:
    owners = entries(section(item, "metadata").get("ownerReferences"))
    names = (str(owner.get("name")) for owner in owners if owner.get("kind") == kind)
    return next(names, None)


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


# Environment variables of a container: name -> value.
type Variables = Mapping[str, str]


def one_off_job(cronjob: JsonObject, job: str, env: Variables) -> dict[str, object]:
    """Return a Job manifest named `job` from the CronJob's template, with env set in each of its containers."""
    spec: dict[str, object] = json.loads(json.dumps(section(cronjob, "spec").get("jobTemplate", {})))["spec"]
    pod = section(section(spec, "template"), "spec")
    for container in entries(pod.get("containers")):
        _set_env(cast("dict[str, object]", container), env)
    metadata = {"name": job, "namespace": metadata_namespace(cronjob)}
    return {"apiVersion": "batch/v1", "kind": "Job", "metadata": metadata, "spec": spec}


def _set_env(container: dict[str, object], env: Variables) -> None:
    """Set the variables in a container's env, replacing any of the same name."""
    kept = [variable for variable in entries(container.get("env")) if variable.get("name") not in env]
    container["env"] = kept + [{"name": name, "value": value} for name, value in env.items()]


def run_cronjob(kube: Kube, cronjob: str, job: str, timeout: int = 300, env: Variables | None = None) -> None:
    """Run the CronJob once now, as Job `job` (env: variables set in its containers); waits, then deletes the Job."""
    if env:
        template = kube.get_json("cronjob", cronjob)
        kube.apply(one_off_job(template, job, env))
    else:
        kube.run("create", "job", job, f"--from=cronjob/{cronjob}")
    try:
        kube.run("wait", "--for=condition=complete", f"job/{job}", f"--timeout={timeout}s", timeout=timeout + 10)
    except KubeError as error:
        error.add_note(_job_log(kube, job))
        raise
    finally:
        kube.delete("job", job)


def cronjob_ending(env: Environment, suffix: str) -> str | None:
    """Return the name of the environment's first CronJob whose name ends with suffix (charts prefix the release)."""
    return next((name for name in map(metadata_name, env.items("cronjobs")) if name.endswith(suffix)), None)


def _job_log(kube: Kube, job: str) -> str:
    """Return the last lines a Job's container wrote; its previous run when it restarts."""
    for previous in ([], ["--previous"]):
        with suppress(KubeError):
            log = kube.run("logs", f"job/{job}", "--tail=60", *previous)
            if log:
                return f"log of job/{job}:\n{log}"
    return f"no log of job/{job}"


def _is_foreign(item: Item) -> bool:
    return metadata_labels(item).get("app") in FOREIGN_APPS


def unready_workloads(items: Sequence[Item]) -> list[str]:
    """Deployments and StatefulSets with fewer ready replicas than wanted, as "name ready/wanted"."""
    found: list[str] = []
    for item in items:
        if _is_foreign(item):
            continue
        replicas = section(item, "spec").get("replicas", 1)
        wanted = replicas if isinstance(replicas, int) else 1
        ready = _int(section(item, "status").get("readyReplicas"))
        if ready < wanted:
            found.append(f"{item.get('kind', '?')}/{metadata_name(item)} {ready}/{wanted}")
    return found


def helm_replicas(env: Environment, namespaces: Sequence[str] | None = None) -> dict[str, int]:
    """Replicas of each Deployment and StatefulSet in the deployed Helm releases, by "namespace/Kind/name".

    Helm keeps a release as base64 of gzipped JSON inside the Secret's base64 data; a manifest without
    replicas means 1.
    """
    found: dict[str, int] = {}
    for namespace in env.namespaces if namespaces is None else namespaces:
        releases = env.kube.get_json("secrets", "-l", "owner=helm,status=deployed", namespace=namespace)
        for secret in entries(releases.get("items")):
            found.update(_release_replicas(secret, namespace))
    return found


def _release_replicas(secret: Item, namespace: str) -> dict[str, int]:
    """Replicas of the Deployments and StatefulSets of the Helm release in this Secret."""
    data = base64.b64decode(base64.b64decode(str(section(secret, "data").get("release", ""))))
    release = section({"release": json.loads(gzip.decompress(data))}, "release")
    found: dict[str, int] = {}
    for doc in entries(list(yaml.safe_load_all(str(release.get("manifest", ""))))):
        if doc.get("kind") in {"Deployment", "StatefulSet"}:
            where = section(doc, "metadata").get("namespace") or release.get("namespace") or namespace
            key = f"{where}/{doc['kind']}/{metadata_name(doc)}"
            found[key] = _int(section(doc, "spec").get("replicas", 1))
    return found


def replica_drift(env: Environment, namespaces: Sequence[str] | None = None) -> list[str]:
    """Workloads whose replicas differ from their Helm release, as "Kind/name live (Helm n)".

    Catches a component a test scaled to 0 and never restored, which unready_workloads counts as 0/0 ready.
    Workloads an autoscaler drives are left out.
    """
    wanted = helm_replicas(env, namespaces)
    autoscalers = env.items("horizontalpodautoscalers", namespaces)
    targets = [(autoscaler, section(section(autoscaler, "spec"), "scaleTargetRef")) for autoscaler in autoscalers]
    autoscaled = {
        f"{metadata_namespace(autoscaler)}/{ref.get('kind')}/{ref.get('name')}" for autoscaler, ref in targets
    }
    found: list[str] = []
    for item in env.workloads(namespaces):
        key = f"{metadata_namespace(item)}/{item.get('kind')}/{metadata_name(item)}"
        if key in wanted and key not in autoscaled:
            live = _int(section(item, "spec").get("replicas", 1))
            if live != wanted[key]:
                name = f"{item.get('kind')}/{metadata_name(item)}"
                found.append(f"{name} {live} (Helm {wanted[key]})")
    return found


def unhealthy_pods(items: Sequence[Item]) -> list[str]:
    """Long-running pods that are not Running with all containers ready, as "name: reason".

    Pods of Jobs are left to failed_jobs; pods being deleted and FOREIGN_APPS are ignored.
    """
    found: list[str] = []
    for pod in items:
        if not _is_left_out(pod):
            found += _pod_problems(pod)
    return found


def _is_left_out(pod: Item) -> bool:
    deleted = bool(section(pod, "metadata").get("deletionTimestamp"))
    return "Job" in _owner_kinds(pod) or deleted or _is_foreign(pod)


def _pod_problems(pod: Item) -> list[str]:
    status = section(pod, "status")
    phase = str(status.get("phase", "Unknown"))
    name = metadata_name(pod)
    if phase not in GOOD_POD_PHASES:
        return [f"{name}: phase {phase}"]
    if phase == "Succeeded":
        return []
    containers = entries(status.get("containerStatuses"))
    unready = [container.get("name", "?") for container in containers if not container.get("ready")]
    return [f"{name}/{container}: not ready" for container in unready]


@dataclass(frozen=True)
class ClusterState:
    """The long-running pods of the environment by uid, and the cluster's nodes."""

    pods: dict[str, Item]
    nodes: frozenset[str]


def cluster_state(env: Environment) -> ClusterState:
    """Return the pods (not of Jobs) and nodes now, to compare with a later state."""
    long_running = [pod for pod in entries(env.items("pods")) if "Job" not in _owner_kinds(pod)]
    pods = {str(section(pod, "metadata").get("uid")): pod for pod in long_running}
    return ClusterState(pods, frozenset(metadata_name(node) for node in env.kube.items("nodes")))


class Disruption(NamedTuple):
    """A pod or node change between two states and when it happened ("" when the cluster does not tell)."""

    at: str
    text: str


def disruptions(before: ClusterState, after: ClusterState) -> list[Disruption]:
    """Nodes and pods that came or went between two states, and containers that restarted."""
    found = [Disruption("", f"node {node} removed") for node in sorted(before.nodes - after.nodes)]
    found += [Disruption("", f"node {node} added") for node in sorted(after.nodes - before.nodes)]
    gone = [pod for uid, pod in before.pods.items() if uid not in after.pods]
    found += [Disruption("", f"pod {_where(pod)} gone") for pod in gone]
    started = [pod for uid, pod in after.pods.items() if uid not in before.pods]
    found += [_started(pod) for pod in started]
    pairs = ((before.pods.get(uid, {}), pod) for uid, pod in after.pods.items())
    return [*found, *chain.from_iterable(starmap(_restarts, pairs))]


def _started(pod: Item) -> Disruption:
    created = str(section(pod, "metadata").get("creationTimestamp", ""))
    return Disruption(created, f"pod {_where(pod)} started {created}")


def _restarts(before: Item, after: Item) -> list[Disruption]:
    """Containers of the pod that restarted between its two states."""
    statuses = entries(section(before, "status").get("containerStatuses"))
    earlier = {str(status.get("name")): _int(status.get("restartCount")) for status in statuses}
    found: list[Disruption] = []
    for container in entries(section(after, "status").get("containerStatuses")):
        name = str(container.get("name"))
        count = _int(container.get("restartCount"))
        restarts = count - earlier.get(name, count)
        if restarts > 0:
            last = section(section(container, "lastState"), "terminated")
            finished = str(last.get("finishedAt", ""))
            reason = f"last: {last.get('reason', '?')} at {finished or '?'}"
            found.append(
                Disruption(finished, f"container {metadata_name(after)}/{name} restarted {restarts}x ({reason})")
            )
    return found


def _where(pod: Item) -> str:
    return f"{metadata_name(pod)} on {section(pod, 'spec').get('nodeName', '?')}"


def _has_failed(job: Item) -> bool:
    return is_condition_true(job, "Failed")


KEYCLOAKS = "keycloaks.k8s.keycloak.org"


def recreate_update_jobs(keycloaks: Sequence[Item]) -> set[str]:
    """Update Jobs of Keycloak CRs that fail by design: exit 3 makes the operator recreate Keycloak.

    Any other exit code gives a different RecreateUpdateUsed message, so a broken update Job still counts.
    """
    return {
        f"{metadata_name(keycloak)}-update-job"
        for keycloak in keycloaks
        for condition in entries(section(keycloak, "status").get("conditions"))
        if condition.get("type") == "RecreateUpdateUsed"
        and condition.get("status") == "True"
        and str(condition.get("message", "")).startswith("Incompatible changes detected")
    }


def failed_jobs(items: Sequence[Item], keycloaks: Sequence[Item] = ()) -> list[str]:
    """Jobs that failed: every standalone Job, and the latest Job of each CronJob; not a `recreate_update_jobs` one."""
    latest: dict[str, Item] = {}
    standalone: list[Item] = []
    for job in items:
        cronjob = _owner_name(job, "CronJob")
        if cronjob is None:
            standalone.append(job)
            continue
        created = str(section(job, "metadata").get("creationTimestamp", ""))
        current = latest.get(cronjob)
        if current is None or created > str(section(current, "metadata").get("creationTimestamp", "")):
            latest[cronjob] = job
    expected = recreate_update_jobs(keycloaks)
    counted = (*standalone, *latest.values())
    return sorted(metadata_name(job) for job in counted if _has_failed(job) and metadata_name(job) not in expected)


@contextmanager
def component_down(env: Environment, http: requests.Session, component: str) -> Generator[None]:
    """Run the block with the component's main deployment stopped and its root failing.

    Afterwards the deployment is restored and the block returns once the root answers again.
    """
    url = env.profile.urls[component]
    with scaled(env.kube, env.deployment_for(component), 0):
        wait_until(
            lambda: not is_root_answering(http, url, ROOT_TIMEOUT), timeout=120, description=f"{component} stopped"
        )
        yield
    wait_until(
        lambda: is_root_answering(http, url, ROOT_TIMEOUT), timeout=300, description=f"{component} answers again"
    )
