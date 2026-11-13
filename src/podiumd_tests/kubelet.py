"""Container metrics of the kubelet, through the API server's node proxy (RBAC: get nodes/proxy).

The kubelet serves them on every cluster, also where Prometheus scrapes neither cAdvisor nor kube-state-metrics.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from podiumd_tests.kube import Kube

# (namespace, pod, container)
type ContainerKey = tuple[str, str, str]

_SERIES = re.compile(r"^(\w+)\{([^}]*)\} (\S+)")
_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')
_QUANTITY = re.compile(r"(\d+(?:\.\d+)?(?:e\d+)?)([KMGTP]i?|k)?")
_FACTORS = {
    "": 1,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
    "P": 1e15,
    **{f"{unit}i": 1024.0 ** (power + 1) for power, unit in enumerate("KMGTP")},
}

RESOURCE = "resource"
CADVISOR = "cadvisor"


def node_metrics(kube: Kube, node: str, endpoint: str) -> str:
    """Return the kubelet's Prometheus text of /metrics/<endpoint> (resource or cadvisor) on the node."""
    return kube.run("get", "--raw", f"/api/v1/nodes/{node}/proxy/metrics/{endpoint}", timeout=60)


def container_values(text: str, metric: str) -> dict[ContainerKey, float]:
    """Return the metric's value per container; series of a whole pod (no container label) are left out."""
    found: dict[ContainerKey, float] = {}
    for line in text.splitlines():
        match = _SERIES.match(line)
        if match is None or match.group(1) != metric:
            continue
        labels = dict(_LABEL.findall(match.group(2)))
        container = labels.get("container")
        if container:
            key = (labels.get("namespace", ""), labels.get("pod", ""), container)
            found[key] = float(match.group(3))
    return found


def quantity_bytes(quantity: str) -> float:
    """Return a Kubernetes memory quantity ("512Mi", "1G", "1e9") in bytes; ValueError otherwise."""
    match = _QUANTITY.fullmatch(quantity.strip())
    if match is None:
        msg = f"memory quantity {quantity!r}: expected a number with an optional unit such as Mi or G"
        raise ValueError(msg)
    return float(match.group(1)) * _FACTORS[match.group(2) or ""]
