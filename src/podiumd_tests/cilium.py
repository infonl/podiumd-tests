"""Cilium, the network plugin of some clusters, and its flow observer Hubble: detected per cluster.

A plain install and Microsoft's AKS build both run the agent as DaemonSet cilium in kube-system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import metadata_name

if TYPE_CHECKING:
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
