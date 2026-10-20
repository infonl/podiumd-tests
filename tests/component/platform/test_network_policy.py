"""Cilium network policy (phase 1): a non-allowlisted pod cannot reach a protected backend.

The chart's ingress allow-lists let only named clients reach redis-ha, Elasticsearch, Solr, ZooKeeper,
OpenBao, frankgateway-etcd, ClamAV and the ZAC office converter. This asserts the policy blocks a pod that
is not on the list, and records the policy drop. Without a drop recorder covering it (recorded_drops here,
not the whole run) the deny would not be visible. Skips where Cilium is absent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.cilium import describe_drops
from podiumd_tests.cilium import recorded_drops
from podiumd_tests.kube import KubeError

if TYPE_CHECKING:
    from pathlib import Path

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("cilium", "cluster")]

# A pod not on any backend allow-list (it has nc); a protected backend and its port.
ATTACKER = "ptest-bootstrap-mock-server"
REDIS = ("redis-ha-master", "6379")


def test_network_policy_blocks_a_non_allowlisted_pod(podiumd_env: Environment, tmp_path: Path) -> None:
    """From a pod off the allow-list a TCP connect to redis-ha is denied, and the drop is recorded."""
    kube = podiumd_env.kube
    host, port = REDIS
    drops = tmp_path / "cilium-drops.jsonl"
    with recorded_drops(kube, drops), pytest.raises(KubeError):  # nc exits non-zero: the SYN is dropped
        kube.run("exec", f"deployment/{ATTACKER}", "--", "nc", "-w", "4", "-z", host, port)
    denied = [line for line in describe_drops(kube, drops) if f":{port}" in line and ATTACKER in line]
    assert denied, (
        f"the blocked connection to {host}:{port} left no policy drop; recorded: {describe_drops(kube, drops)}"
    )
