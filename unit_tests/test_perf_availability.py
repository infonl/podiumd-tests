"""Unit tests for the availability gate of the perf tier."""

import json

from datetime import UTC
from datetime import datetime

import pytest

from podiumd_tests.capabilities import Capabilities
from podiumd_tests.config import REPO_ROOT
from podiumd_tests.kubelet import ContainerKey
from podiumd_tests.perf.availability import Limits
from podiumd_tests.perf.availability import Sample
from podiumd_tests.perf.availability import Values
from podiumd_tests.perf.availability import Watch
from podiumd_tests.perf.availability import availability_limits
from podiumd_tests.perf.availability import memory_limits
from podiumd_tests.perf.availability import throttled_shares
from podiumd_tests.perf.availability import watched
from podiumd_tests.perf.availability_report import Event
from podiumd_tests.perf.availability_report import availability
from podiumd_tests.perf.availability_report import failure_bursts
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.perf.availability_report import report
from podiumd_tests.perf.availability_report import timeline
from podiumd_tests.perf.availability_report import unhealthy_runs
from podiumd_tests.workloads import Disruption

LIMITS = Limits(health_interval_s=0.01, recovery_s=1, min_available=0.9, max_memory_ratio=0.9)
KEY: ContainerKey = ("podiumd", "openzaak-1", "openzaak")
MIB = 1024 * 1024
# 2026-11-14T10:00:00Z
T0 = 1794650400
HEADER = "Timestamp,User Count,Type,Name,Requests/s,Failures/s,Total Request Count,Total Failure Count"


def history(*rows):
    """Locust's stats history: (second, name, total failures) rows."""
    return "\n".join([HEADER, *(f"{T0 + s},5,API,{name},1,0,10,{failures}" for s, name, failures in rows)])


def at(second):
    return T0 + second


def test_limits_come_from_perf_yaml():
    assert availability_limits(REPO_ROOT / "perf.yaml").min_available == pytest.approx(0.99)


def test_failure_bursts_merge_close_seconds_and_survive_a_stats_reset():
    rows = [
        (0, "oz_zaken", 0),
        (1, "oz_zaken", 2),
        (1, "Aggregated", 2),
        (3, "oz_zaak_create", 1),
        (4, "oz_zaken", 3),
        (20, "oz_zaken", 1),  # Locust's stats reset: the total starts again
    ]
    assert failure_bursts(history(*rows)) == [
        Event(at(1), at(4), "4 failed requests (oz_zaken 3, oz_zaak_create 1)"),
        Event(at(20), at(20), "1 failed requests (oz_zaken 1)"),
    ]


def test_unhealthy_runs_end_at_a_healthy_sample():
    samples = [
        Sample(at(0), "zac", None),
        Sample(at(5), "zac", "HTTP 503"),
        Sample(at(10), "zac", "ReadTimeout"),
        Sample(at(15), "zac", None),
        Sample(at(20), "kiss", "HTTP 502"),
    ]
    assert unhealthy_runs(samples) == [
        Event(at(20), at(20), "kiss root: HTTP 502 in 1 samples"),
        Event(at(5), at(10), "zac root: HTTP 503, ReadTimeout in 2 samples"),
    ]
    assert availability(samples) == {"zac": (2, 4), "kiss": (0, 1)}


def test_throttled_shares_count_the_periods_between_two_readings():
    before: list[Values] = [{KEY: 10.0}, {KEY: 100.0}]
    after: list[Values] = [{KEY: 40.0}, {KEY: 200.0, ("podiumd", "zac-1", "zac"): 50.0}]
    assert throttled_shares(before, after) == {KEY: 0.3}


def test_memory_limits_per_container():
    pod = {
        "metadata": {"name": "openzaak-1", "namespace": "podiumd"},
        "spec": {
            "containers": [
                {"name": "openzaak", "resources": {"limits": {"memory": "1Gi"}}},
                {"name": "nginx", "resources": {}},
            ]
        },
    }
    assert memory_limits([pod]) == {KEY: 1024**3, ("podiumd", "openzaak-1", "nginx"): None}


def watch(**fields):
    found = Watch(frozenset(("openzaak", "zac")), LIMITS, started=at(0), ended=at(60))
    for name, value in fields.items():
        setattr(found, name, value)
    return found


def test_problems_name_restarts_unready_pods_unavailability_and_memory():
    restart = Disruption("2026-11-14T10:00:30Z", "container openzaak-1/openzaak restarted 1x (last: OOMKilled at x)")
    found = watch(
        disruptions=[restart],
        unready=["zac-1/zac: not ready"],
        samples=[Sample(at(0), "zac", None), Sample(at(5), "zac", "HTTP 503")],
        memory={KEY: 950 * MIB},
        memory_limits={KEY: 1000 * MIB},
    )
    assert problems(found) == [
        "container openzaak-1/openzaak restarted 1x (last: OOMKilled at x) during the load",
        "zac-1/zac: not ready not Ready 1s after the load",
        "zac root healthy in 1 of 2 samples < 90%",
        "openzaak-1/openzaak peak memory 950 MiB = 95% of its limit > 90%",
    ]


QUIET_REPORT = """Load 10:00:00-10:01:00 UTC; Ready again 2 s after it.

| Component | Healthy root answers | Highest share of a memory limit | Largest working set |
|---|---|---|---|
| openzaak | 1/1 | 50% (openzaak-1/openzaak) | 512 MiB (openzaak-1/openzaak) |
| zac | 1/1 | - | 300 MiB (zac-1/zac, no limit) |

No failed requests, failing root answers or pod changes.

No memory limit: zac-1/zac.

Not measured: CPU throttling: kubelet cAdvisor metrics unreadable: forbidden."""


def test_a_quiet_load_has_no_problems_and_says_so():
    found = watch(
        samples=[Sample(at(0), "zac", None), Sample(at(0), "openzaak", None)],
        memory={KEY: 512 * MIB, ("podiumd", "zac-1", "zac"): 300 * MIB},
        memory_limits={KEY: 1024 * MIB, ("podiumd", "zac-1", "zac"): None},
        recovered_s=2.0,
        notes=["CPU throttling: kubelet cAdvisor metrics unreadable: forbidden"],
    )
    assert problems(found) == []
    assert report(found, HEADER) == QUIET_REPORT


def test_timeline_puts_bursts_next_to_restarts_and_untimed_changes_last():
    found = watch(
        disruptions=[
            Disruption("", "pod zac-1 on n1 gone"),
            Disruption("2026-11-14T10:00:03Z", "container openzaak-1/openzaak restarted 1x"),
        ],
        samples=[Sample(at(5), "openzaak", "HTTP 502"), Sample(at(10), "openzaak", None)],
    )
    events = timeline(found, history((2, "oz_zaken", 4)))
    assert [event.text for event in events] == [
        "4 failed requests (oz_zaken 4)",
        "container openzaak-1/openzaak restarted 1x",
        "openzaak root: HTTP 502 in 1 samples",
        "pod zac-1 on n1 gone",
    ]
    lines = report(found, history((2, "oz_zaken", 4))).splitlines()
    assert "| 10:00:03 | container openzaak-1/openzaak restarted 1x |" in lines
    assert "| ? | pod zac-1 on n1 gone |" in lines


METRICS = """container_memory_working_set_bytes{container="openzaak",namespace="podiumd",pod="openzaak-1"} 3e+08 1
container_memory_working_set_bytes{container="kiss",namespace="podiumd",pod="kiss-1"} 9e+08 1
container_cpu_cfs_throttled_periods_total{container="openzaak",namespace="podiumd",pod="openzaak-1"} 5 1
container_cpu_cfs_periods_total{container="openzaak",namespace="podiumd",pod="openzaak-1"} 100 1
"""


def cluster_pod(name, *, restarts=0):
    return {
        "metadata": {"uid": name, "name": name, "namespace": "podiumd", "ownerReferences": [{"kind": "ReplicaSet"}]},
        "spec": {
            "nodeName": "n1",
            "containers": [{"name": name.split("-")[0], "resources": {"limits": {"memory": "1Gi"}}}],
        },
        "status": {"phase": "Running", "containerStatuses": [{"name": "app", "ready": True, "restartCount": restarts}]},
    }


def test_watched_samples_the_roots_and_memory_of_the_loaded_components(env_factory, fake_runner, fake_http):
    pods = {"items": [cluster_pod("openzaak-1"), cluster_pod("kiss-1")]}
    fake_runner.answers = {
        "get pods": (0, json.dumps(pods)),
        "get nodes": (0, json.dumps({"items": [{"metadata": {"name": "n1"}}]})),
        "get --raw": (0, METRICS),
    }
    fake_http({"/": (200, {})})
    env = env_factory()
    env.capabilities = Capabilities(frozenset(("cluster", "openzaak")), {})
    with watched(env, ["openzaak", "zac"], LIMITS) as found:
        assert found.components == frozenset(("openzaak",))  # zac has no URL in the profile
    assert found.samples
    assert {sample.problem for sample in found.samples} == {None}
    assert found.memory == {KEY: 3e8}
    assert found.memory_limits == {KEY: 1024**3}
    assert found.throttled == {}  # no CFS period passed between the two readings
    assert found.recovered_s is not None
    assert found.started > datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    assert found.ended >= found.started
    assert problems(found) == []


def test_watched_without_cluster_access_only_samples_the_roots(env_factory, fake_http):
    fake_http({"/": (503, {})})
    env = env_factory()
    env.capabilities = Capabilities(frozenset(("openzaak",)), {"cluster": "kubectl failed"})
    with watched(env, ["openzaak"], LIMITS) as found:
        assert found.components == frozenset(("openzaak",))
    assert {sample.problem for sample in found.samples} == {"HTTP 503"}
    assert found.notes == ["pods, restarts and memory: the environment has no cluster access"]
    assert problems(found) == [f"openzaak root healthy in 0 of {len(found.samples)} samples < 90%"]
