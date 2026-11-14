"""Availability of the loaded components during and after a Locust run, against perf.yaml's `availability`.

During the run: each component's root at an interval, and the RSS and working set of its containers from the
kubelet's cAdvisor. Afterwards: its pods Ready again within recovery_s, with no restart or replacement
(workloads.disruptions).
"""

from __future__ import annotations

import threading
import time

from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.background import running
from podiumd_tests.capabilities import CLUSTER
from podiumd_tests.components import deployed_components
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_name
from podiumd_tests.kube import metadata_namespace
from podiumd_tests.kubelet import CADVISOR
from podiumd_tests.kubelet import ContainerKey
from podiumd_tests.kubelet import container_values
from podiumd_tests.kubelet import node_metrics
from podiumd_tests.kubelet import quantity_bytes
from podiumd_tests.kubelet import quantity_cores
from podiumd_tests.perf.stats import perf_settings
from podiumd_tests.responses import root_problem
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import ROOT_TIMEOUT
from podiumd_tests.workloads import ClusterState
from podiumd_tests.workloads import Disruption
from podiumd_tests.workloads import cluster_state
from podiumd_tests.workloads import disruptions
from podiumd_tests.workloads import unhealthy_pods

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator
    from collections.abc import Iterable
    from collections.abc import Mapping
    from collections.abc import Sequence
    from pathlib import Path

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

RSS = "container_memory_rss"
WORKING_SET = "container_memory_working_set_bytes"
THROTTLED = "container_cpu_cfs_throttled_periods_total"
PERIODS = "container_cpu_cfs_periods_total"
NO_CLUSTER = "pods, restarts and memory: the environment has no cluster access"

# A value per container.
type Values = dict[ContainerKey, float]


@dataclass(frozen=True)
class Limits:
    """perf.yaml's `availability`: what a Locust run may do to the components it loads."""

    health_interval_s: float
    recovery_s: float
    min_available: float
    max_memory_ratio: float


def availability_limits(path: Path) -> Limits:
    """Return the availability limits of perf.yaml."""
    data = cast("dict[str, float]", perf_settings(path)["availability"])
    return Limits(
        float(data["health_interval_s"]),
        float(data["recovery_s"]),
        float(data["min_available"]),
        float(data["max_memory_ratio"]),
    )


@dataclass(frozen=True)
class Sample:
    """One GET of a component's root: when (Unix seconds) and why it failed (None: healthy)."""

    at: float
    component: str
    problem: str | None


@dataclass
class Watch:  # pylint: disable=too-many-instance-attributes  # one field per measurement
    """What `watched` measured of the loaded components; complete once its block has ended."""

    components: frozenset[str]
    limits: Limits
    started: float = 0
    ended: float = 0
    samples: list[Sample] = field(default_factory=list[Sample])
    # Highest RSS and working set seen per container, in bytes, and its memory limit (None: no limit). Only RSS
    # (anonymous memory) counts against the limit: the kernel reclaims the page cache in the working set first.
    rss: Values = field(default_factory=dict[ContainerKey, float])
    working_set: Values = field(default_factory=dict[ContainerKey, float])
    memory_limits: dict[ContainerKey, float | None] = field(default_factory=dict[ContainerKey, float | None])
    # In cores; None: no limit.
    cpu_limits: dict[ContainerKey, float | None] = field(default_factory=dict[ContainerKey, float | None])
    # Share of CFS periods in which the container was throttled, for containers with a CPU limit.
    throttled: Values = field(default_factory=dict[ContainerKey, float])
    disruptions: list[Disruption] = field(default_factory=list[Disruption])
    unready_before: list[str] = field(default_factory=list[str])
    unready: list[str] = field(default_factory=list[str])
    recovered_s: float | None = None
    # What was not measured, and why.
    notes: list[str] = field(default_factory=list[str])


def is_loaded(pod: str, components: frozenset[str]) -> bool:
    """Whether the pod of this name belongs to one of the components, by its deployment prefix."""
    return bool(deployed_components([pod]) & components)


def throttled_shares(before: Sequence[Values], after: Sequence[Values]) -> Values:
    """Return the share of CFS periods each container was throttled in between two [throttled, periods] readings."""
    throttled_before, periods_before = before
    throttled_after, periods_after = after
    found: Values = {}
    for key, periods in periods_after.items():
        ran = periods - periods_before.get(key, 0)
        if ran > 0 and key in throttled_after:
            found[key] = (throttled_after[key] - throttled_before.get(key, 0)) / ran
    return found


def resource_limits(
    pods: Iterable[JsonObject], resource: str, parse: Callable[[str], float]
) -> dict[ContainerKey, float | None]:
    """Return each container's limit of the resource ("memory", "cpu") in the pods, parsed; None without one."""
    found: dict[ContainerKey, float | None] = {}
    for pod in pods:
        for container in entries(section(pod, "spec").get("containers")):
            limit = section(section(container, "resources"), "limits").get(resource)
            key = (metadata_namespace(pod), metadata_name(pod), str(container.get("name")))
            found[key] = parse(str(limit)) if limit else None
    return found


def _sample_root(session: requests.Session, url: str, component: str, watch: Watch, stop: threading.Event) -> None:
    while True:
        watch.samples.append(Sample(time.time(), component, root_problem(session, url, ROOT_TIMEOUT)))
        if stop.wait(watch.limits.health_interval_s):
            return


class _Cluster:
    """The loaded components' pods: their state before the load, memory during it and recovery after it."""

    def __init__(self, env: Environment, watch: Watch) -> None:
        self.env: Environment = env
        self.watch: Watch = watch
        self.before: ClusterState = self.loaded_state()
        pods = list(self.before.pods.values())
        watch.unready_before = unhealthy_pods(pods)
        self.nodes: list[str] = sorted({str(section(pod, "spec").get("nodeName")) for pod in pods})
        self.cpu_before: list[Values] | None = self.cpu_counters()

    def loaded_state(self) -> ClusterState:
        """Return the cluster state with only the loaded components' pods."""
        state = cluster_state(self.env)
        pods = {uid: pod for uid, pod in state.pods.items() if self.is_mine(metadata_name(pod))}
        return ClusterState(pods, state.nodes)

    def is_mine(self, pod: str) -> bool:
        """Whether the pod of this name belongs to a loaded component."""
        return is_loaded(pod, self.watch.components)

    def metrics(self, endpoint: str, names: Sequence[str]) -> list[Values]:
        """Return each metric's values of the loaded containers on the nodes."""
        texts = [node_metrics(self.env.kube, node, endpoint) for node in self.nodes]
        return [self.mine(texts, name) for name in names]

    def mine(self, texts: Sequence[str], name: str) -> Values:
        """Return the metric's values of the loaded containers in the kubelets' texts."""
        values = (container_values(text, name) for text in texts)
        return {key: value for found in values for key, value in found.items() if self.is_mine(key[1])}

    def cpu_counters(self) -> list[Values] | None:
        """Return the [throttled, periods] CFS counters of the loaded containers; None when unreadable."""
        try:
            return self.metrics(CADVISOR, (THROTTLED, PERIODS))
        except KubeError as error:
            self.watch.notes.append(f"CPU throttling: kubelet cAdvisor metrics unreadable: {error}")
            return None

    def sample_memory(self, stop: threading.Event) -> None:
        """Keep the highest RSS and working set per loaded container until stop is set."""
        peaks = (self.watch.rss, self.watch.working_set)
        while True:
            try:
                readings = self.metrics(CADVISOR, (RSS, WORKING_SET))
            except KubeError as error:
                self.watch.notes.append(f"memory: kubelet cAdvisor metrics unreadable (needs get nodes/proxy): {error}")
                return
            for peak, values in zip(peaks, readings, strict=True):
                _keep_highest(peak, values)
            if stop.wait(self.watch.limits.health_interval_s):
                return

    def unready(self) -> list[str]:
        """Return the loaded pods that are not Running and Ready."""
        return unhealthy_pods([pod for pod in self.env.items("pods") if self.is_mine(metadata_name(pod))])

    def recover(self) -> None:
        """Wait for the loaded pods to be Ready, then record what changed and the CPU throttling."""
        watch = self.watch
        try:
            wait_until(lambda: not self.unready(), timeout=watch.limits.recovery_s, description="the loaded pods Ready")
        except WaitTimeoutError:
            watch.unready = self.unready()
        else:
            watch.recovered_s = time.time() - watch.ended
        after = self.loaded_state()
        watch.disruptions = disruptions(self.before, after)
        watch.memory_limits = resource_limits(after.pods.values(), "memory", quantity_bytes)
        watch.cpu_limits = resource_limits(after.pods.values(), "cpu", quantity_cores)
        cpu_after = None if self.cpu_before is None else self.cpu_counters()
        if self.cpu_before is not None and cpu_after is not None:
            watch.throttled = throttled_shares(self.cpu_before, cpu_after)


def _keep_highest(peak: Values, values: Values) -> None:
    for key, value in values.items():
        peak[key] = max(value, peak.get(key, 0))


def _stop(threads: list[threading.Thread], stop: threading.Event, watch: Watch) -> None:
    stop.set()
    for thread in threads:
        thread.join()
    watch.ended = time.time()


@contextmanager
def watched(env: Environment, urls: Mapping[str, str], components: Iterable[str], limits: Limits) -> Generator[Watch]:
    """Measure the components' availability while the block runs a load, and their recovery after it.

    urls: the component URLs as this console reaches them (the `urls` fixture).
    """
    watch = Watch(frozenset(component for component in components if component in urls), limits)
    stop = threading.Event()
    threads = [
        threading.Thread(target=_sample_root, args=(env.session(), urls[name], name, watch, stop), daemon=True)
        for name in sorted(watch.components)
    ]
    cluster = _Cluster(env, watch) if CLUSTER in env.capabilities.present else None
    if cluster is None:
        watch.notes.append(NO_CLUSTER)
    else:
        threads.append(threading.Thread(target=cluster.sample_memory, args=(stop,), daemon=True))
    watch.started = time.time()
    with running(threads, lambda: _stop(threads, stop, watch)):
        yield watch
    if cluster is not None:
        cluster.recover()
