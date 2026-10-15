"""Cilium, the network plugin of some clusters, and its flow observer Hubble: detected per cluster.

A plain install and Microsoft's AKS build both run the agent as DaemonSet cilium in kube-system.
"""

from __future__ import annotations

import json
import threading

from contextlib import contextmanager
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_name
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
    """The Cilium agent pods, one per node."""
    return entries(kube.get_json("pods", "-l", AGENT_SELECTOR, namespace=NAMESPACE).get("items"))


def detect_network(kube: Kube) -> tuple[frozenset[str], dict[str, str]]:
    """The present network capabilities (cilium, hubble), and why the others are absent."""
    try:
        agents = agent_pods(kube)
        services = {metadata_name(s) for s in kube.items("services", namespace=NAMESPACE)}
    except KubeError as exc:
        reason = f"cannot read namespace {NAMESPACE}: {exc}"
        return frozenset(), {CILIUM: reason, HUBBLE: reason}
    present: set[str] = set()
    reasons: dict[str, str] = {}
    if agents:
        present.add(CILIUM)
    else:
        reasons[CILIUM] = f"no pods {AGENT_SELECTOR} in {NAMESPACE}"
    if HUBBLE_RELAY in services:
        present.add(HUBBLE)
    else:
        reasons[HUBBLE] = f"no Service {HUBBLE_RELAY} in {NAMESPACE}"
    return frozenset(present), reasons


@contextmanager
def recorded_drops(kube: Kube, path: Path) -> Generator[None]:
    """Write the packets a policy denied to path, one JSON object per line, while the context is open.

    cilium-dbg monitor events carry no time; each line gets "time", when it was read.
    """
    commands = [
        kube.command("exec", metadata_name(p), "-c", "cilium-agent", "--", *MONITOR, namespace=NAMESPACE)
        for p in agent_pods(kube)
    ]
    processes = [start_process(c) for c in commands]
    lock = threading.Lock()
    with path.open("w", encoding="utf-8") as out:

        def copy(process: subprocess.Popen[str]) -> None:
            for line in process.stdout or ():
                event = policy_drop(line)
                if event is not None:
                    with lock:
                        out.write(json.dumps({"time": datetime.now(UTC).isoformat(timespec="seconds"), **event}) + "\n")
                        out.flush()

        threads = [threading.Thread(target=copy, args=(p,), daemon=True) for p in processes]
        for thread in threads:
            thread.start()
        try:
            yield
        finally:
            for process in processes:
                process.terminate()
            for thread in threads:
                thread.join(5)


MONITOR = ("cilium-dbg", "monitor", "--type", "drop", "--json")


def policy_drop(line: str) -> JsonObject | None:
    """The monitor event of a policy denial; None for other drops (e.g. IPv6 router solicitations) and chatter."""
    if not line.startswith("{"):
        return None
    try:
        found = entries([json.loads(line)])
    except json.JSONDecodeError:
        return None
    return found[0] if found and str(found[0].get("reason", "")).startswith("Policy") else None


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
        str(section(p, "status").get("podIP")): f"{section(p, 'metadata').get('namespace')}/{metadata_name(p)}"
        for p in kube.items("pods", all_namespaces=True)
    }
    seen: dict[str, tuple[str, int]] = {}
    for event in events:
        summary = section(event, "summary")
        l3, l4 = section(summary, "l3"), section(summary, "l4")
        source, destination = (pods.get(str(l3.get(k)), str(l3.get(k, "?"))) for k in ("src", "dst"))
        port = f":{l4['dst']}" if l4.get("dst") else ""
        key = f"{source} -> {destination}{port} {event.get('reason')}"
        first, count = seen.get(key, (str(event.get("time")), 0))
        seen[key] = (first, count + 1)
    return [f"{first} {key} ({count}x)" for key, (first, count) in seen.items()]
