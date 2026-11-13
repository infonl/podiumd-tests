"""Cilium, the network plugin of some clusters, and its flow observer Hubble: detected per cluster.

A plain install and Microsoft's AKS build both run the agent as DaemonSet cilium in kube-system.
"""

from __future__ import annotations

import json
import os
import threading

from contextlib import contextmanager
from contextlib import suppress
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

from podiumd_tests.background import running
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_name
from podiumd_tests.kube import metadata_namespace
from podiumd_tests.process import start_process

if TYPE_CHECKING:
    import subprocess  # nosec B404  # type only

    from collections.abc import Generator
    from pathlib import Path

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.kube import Kube

CILIUM = "cilium"
HUBBLE = "hubble"
NAMESPACE = "kube-system"
AGENT_SELECTOR = "k8s-app=cilium"
HUBBLE_RELAY = "hubble-relay"


def agent_pods(kube: Kube) -> list[JsonObject]:
    """Return the Cilium agent pods, one per node."""
    return entries(kube.get_json("pods", "-l", AGENT_SELECTOR, namespace=NAMESPACE).get("items"))


def detect_network(kube: Kube) -> tuple[frozenset[str], dict[str, str]]:
    """Return the present network capabilities (cilium, hubble), and why the others are absent."""
    try:
        agents, services = agent_pods(kube), kube.items("services", namespace=NAMESPACE)
    except KubeError as exc:
        reason = f"cannot read namespace {NAMESPACE}: {exc}"
        return frozenset(), {CILIUM: reason, HUBBLE: reason}
    present: set[str] = set()
    reasons: dict[str, str] = {}
    if agents:
        present.add(CILIUM)
    else:
        reasons[CILIUM] = f"no pods {AGENT_SELECTOR} in {NAMESPACE}"
    if HUBBLE_RELAY in {metadata_name(service) for service in services}:
        present.add(HUBBLE)
    else:
        reasons[HUBBLE] = f"no Service {HUBBLE_RELAY} in {NAMESPACE}"
    return frozenset(present), reasons


@contextmanager
def recorded_drops(kube: Kube, path: Path) -> Generator[None]:
    """Write the packets a policy denied to path, one JSON object per line, while the context is open.

    cilium-dbg monitor events carry no time; each line gets "time", when it was read.

    kubectl exec leaves the remote cilium-dbg monitor running when the local client stops, because the
    monitor writes only on a drop and so never sees the closed stdout: a quiet run would leak one process
    per node. Two best-effort stops: the monitor runs on a pty (kubectl exec -t), so killing the local
    kubectl hangs up the pty (SIGHUP); and a pkill afterwards, where the image has it. A run with drops
    self-clears (the monitor hits EPIPE on the next write). The distroless AKS agent image honours neither
    the hangup nor has pkill, so a quiet run there retains the monitor until the agent recycles (it
    reinstalls often); its cilium-dbg should exit on EPIPE/SIGHUP (upstream).
    """
    pods = agent_pods(kube)
    monitors = [start_monitor(kube, metadata_name(pod)) for pod in pods]
    lock = threading.Lock()
    with path.open("w", encoding="utf-8") as out:

        def copy(monitor: Monitor) -> None:
            for record in _drop_records(monitor):
                with lock:
                    out.write(record)
                    out.flush()

        threads = [threading.Thread(target=copy, args=(monitor,), daemon=True) for monitor in monitors]
        with running(threads, lambda: _stop_monitors(kube, pods, monitors, threads)):
            yield


def _drop_records(monitor: Monitor) -> Generator[str]:
    """Each policy drop of the monitor as a JSON line, with the time it was read."""
    for line in monitor.lines():
        event = policy_drop(line)
        if event is not None:
            stamped = {"time": datetime.now(UTC).isoformat(timespec="seconds"), **event}
            yield f"{json.dumps(stamped)}\n"


def _stop_monitors(
    kube: Kube, pods: list[JsonObject], monitors: list[Monitor], readers: list[threading.Thread]
) -> None:
    for monitor in monitors:
        monitor.stop()
    for pod in pods:
        with suppress(KubeError):
            kube.run(
                "exec",
                metadata_name(pod),
                "-c",
                "cilium-agent",
                "--",
                "pkill",
                "-f",
                " ".join(MONITOR),
                namespace=NAMESPACE,
            )
    for reader in readers:
        reader.join(5)


MONITOR = ("cilium-dbg", "monitor", "--type", "drop", "--json")


class Monitor:
    """A cilium-dbg monitor on one agent pod, read over a pty so the remote gets SIGHUP when kubectl stops."""

    def __init__(self, process: subprocess.Popen[str], master: int) -> None:
        self._process: subprocess.Popen[str] = process
        self._master: int = master  # the pty master; lines() owns and closes it

    def lines(self) -> Generator[str]:
        """Yield the monitor's output lines until it stops; killing kubectl closes the pty and ends the stream."""
        with suppress(OSError), os.fdopen(self._master, encoding="utf-8", errors="replace") as reader:
            yield from reader

    def stop(self) -> None:
        """Kill the local kubectl; with -t the exec stream closes, so the remote monitor gets SIGHUP.

        Only lines() closes the pty master, when kubectl's death ends the stream: closing it here too would
        double-close the fd. kill (not terminate) so a kubectl that ignores SIGTERM still drops the stream.
        """
        self._process.kill()


def start_monitor(kube: Kube, pod: str) -> Monitor:
    """Start cilium-dbg monitor in an agent pod on a pty (kubectl exec -t), reading its drops."""
    master, slave = os.openpty()
    command = kube.command("exec", "-i", "-t", pod, "-c", "cilium-agent", "--", *MONITOR, namespace=NAMESPACE)
    process = start_process(command, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    return Monitor(process, master)


def policy_drop(line: str) -> JsonObject | None:
    """Return the monitor event of a policy drop; None for other drops (e.g. IPv6 router solicitations) and chatter."""
    if not line.startswith("{"):
        return None
    try:
        found = entries([json.loads(line)])
    except json.JSONDecodeError:
        return None
    event: JsonObject = found[0] if found else {}
    return event if str(event.get("reason", "")).startswith("Policy") else None


def describe_drops(kube: Kube, path: Path) -> list[str]:
    """One line per distinct recorded policy drop: "first time source -> destination:port reason (count)".

    Pod IPs show as namespace/pod; TCP retries repeat the same drop, so they are counted, not listed.
    """
    if not path.exists():
        return []
    events = entries([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line])
    if not events:
        return []
    pods = {
        str(section(pod, "status").get("podIP")): f"{metadata_namespace(pod)}/{metadata_name(pod)}"
        for pod in kube.items("pods", all_namespaces=True)
    }
    seen: dict[str, tuple[str, int]] = {}
    for event in events:
        summary = section(event, "summary")
        l3, l4 = section(summary, "l3"), section(summary, "l4")
        source, destination = (_endpoint(pods, l3, end) for end in ("src", "dst"))
        port = f":{l4['dst']}" if l4.get("dst") else ""
        key = f"{source} -> {destination}{port} {event.get('reason')}"
        first, count = seen.get(key, (str(event.get("time")), 0))
        seen[key] = (first, count + 1)
    return [f"{first} {key} ({count}x)" for key, (first, count) in seen.items()]


def _endpoint(pods: dict[str, str], l3: JsonObject, end: str) -> str:
    """namespace/pod of the src or dst address, else the address."""
    return pods.get(str(l3.get(end)), str(l3.get(end, "?")))
