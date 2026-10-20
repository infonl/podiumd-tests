"""Cilium is the CNI dataplane and service proxy. Ported from podiumd-infra tests/test_cni.py.

Cilium replaces kube-proxy and enforces NetworkPolicies, with no Hubble and no L7 proxy. The routing and
IPAM differ per infrastructure (AKS uses Azure's native routing and delegated IPAM), so those are checked
only on an AKS estate. Skips where the cluster has no Cilium (network_dataplane=azure, or minikube without it).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.smoke, pytest.mark.requires("cilium")]

KUBE_SYSTEM = "kube-system"
# Keys every Cilium estate sets; routing-mode and ipam are infrastructure-specific (checked on AKS only).
POLICY_CONFIG = {
    "kube-proxy-replacement": "true",
    "enable-k8s-networkpolicy": "true",
    "enable-l7-proxy": "false",
    "enable-hubble": "false",
}
AKS_CONFIG = {"routing-mode": "native", "ipam": "delegated-plugin"}


def test_cilium_replaces_kube_proxy(podiumd_env: Environment) -> None:
    """Cilium is the service proxy: no kube-proxy DaemonSet, and every Cilium agent pod is ready."""
    daemonsets = {metadata_name(d): d for d in podiumd_env.kube.items("daemonsets", namespace=KUBE_SYSTEM)}
    assert "kube-proxy" not in daemonsets
    status = section(daemonsets["cilium"], "status")
    assert int(str(status.get("desiredNumberScheduled"))) > 0
    assert status.get("numberReady") == status.get("desiredNumberScheduled")


def test_cilium_config(podiumd_env: Environment) -> None:
    """cilium-config enforces the policy intent; on AKS it also uses Azure's native routing and delegated IPAM."""
    config = section(podiumd_env.kube.get_json("configmap", "cilium-config", namespace=KUBE_SYSTEM), "data")
    wrong = {k: config.get(k) for k, want in POLICY_CONFIG.items() if config.get(k) != want}
    assert not wrong, f"cilium-config policy keys off: {wrong}"
    if podiumd_env.profile.kube.aks:
        wrong_aks = {k: config.get(k) for k, want in AKS_CONFIG.items() if config.get(k) != want}
        assert not wrong_aks, f"cilium-config AKS keys off: {wrong_aks}"
