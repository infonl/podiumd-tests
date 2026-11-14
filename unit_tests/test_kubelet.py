"""Unit tests for the kubelet's container metrics."""

import pytest

from podiumd_tests.kube import Kube
from podiumd_tests.kubelet import container_values
from podiumd_tests.kubelet import node_metrics
from podiumd_tests.kubelet import quantity_bytes
from podiumd_tests.kubelet import quantity_cores

TEXT = """# HELP container_memory_working_set_bytes [STABLE] Current working set of the container in bytes
# TYPE container_memory_working_set_bytes gauge
container_memory_working_set_bytes{container="openzaak",namespace="podiumd",pod="openzaak-1"} 5.1e+08 1794612063153
container_memory_working_set_bytes{container="",namespace="podiumd",pod="openzaak-1"} 6e+08 1794612063153
pod_memory_working_set_bytes{namespace="podiumd",pod="openzaak-1"} 6e+08 1794612063153
"""


def test_container_values_leave_out_pod_series_and_other_metrics():
    assert container_values(TEXT, "container_memory_working_set_bytes") == {
        ("podiumd", "openzaak-1", "openzaak"): 5.1e8
    }


@pytest.mark.parametrize(
    ("quantity", "expected"), [("512Mi", 512 * 1024**2), ("1Gi", 1024**3), ("1G", 1e9), ("1500k", 1.5e6), ("1e9", 1e9)]
)
def test_quantity_bytes(quantity, expected):
    assert quantity_bytes(quantity) == expected


@pytest.mark.parametrize(("quantity", "expected"), [("500m", 0.5), ("2", 2.0), ("1.5", 1.5)])
def test_quantity_cores(quantity, expected):
    assert quantity_cores(quantity) == expected


def test_an_unknown_quantity_is_an_error():
    with pytest.raises(ValueError, match="memory quantity"):
        quantity_bytes("lots")


def test_node_metrics_go_through_the_api_server_proxy(fake_runner):
    fake_runner.answers = {"get --raw": (0, TEXT)}
    assert node_metrics(Kube("ctx", "podiumd", fake_runner), "minikube", "resource") == TEXT
    assert fake_runner.calls[0][-2:] == ["--raw", "/api/v1/nodes/minikube/proxy/metrics/resource"]
