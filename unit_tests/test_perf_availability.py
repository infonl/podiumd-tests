"""Unit tests for the availability gate of the perf tier."""

import json
import sys

from datetime import UTC
from datetime import datetime

import pytest

from podiumd_tests.capabilities import Capabilities
from podiumd_tests.config import REPO_ROOT
from podiumd_tests.kubelet import ContainerKey
from podiumd_tests.kubelet import quantity_bytes
from podiumd_tests.kubelet import quantity_cores
from podiumd_tests.perf.availability import Limits
from podiumd_tests.perf.availability import Sample
from podiumd_tests.perf.availability import Series
from podiumd_tests.perf.availability import Values
from podiumd_tests.perf.availability import Watch
from podiumd_tests.perf.availability import availability_limits
from podiumd_tests.perf.availability import resource_limits
from podiumd_tests.perf.availability import throttled_shares
from podiumd_tests.perf.availability import watched
from podiumd_tests.perf.availability import watched_run
from podiumd_tests.perf.availability_report import Event
from podiumd_tests.perf.availability_report import Trend
from podiumd_tests.perf.availability_report import availability
from podiumd_tests.perf.availability_report import capacity
from podiumd_tests.perf.availability_report import failure_bursts
from podiumd_tests.perf.availability_report import growth_per_min
from podiumd_tests.perf.availability_report import memory_trend
from podiumd_tests.perf.availability_report import memory_trends
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.perf.availability_report import report
from podiumd_tests.perf.availability_report import timeline
from podiumd_tests.perf.availability_report import unhealthy_runs
from podiumd_tests.perf.stats import EndpointStats
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import Disruption

LIMITS = Limits(
    health_interval_s=0.01,
    recovery_s=1,
    min_available=0.9,
    max_memory_ratio=0.9,
    memory_warmup_s=300,
    max_rss_growth_mib_per_min=1,
)
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


def test_resource_limits_per_container():
    pod = {
        "metadata": {"name": "openzaak-1", "namespace": "podiumd"},
        "spec": {
            "containers": [
                {"name": "openzaak", "resources": {"limits": {"memory": "1Gi", "cpu": "500m"}}},
                {"name": "nginx", "resources": {}},
            ]
        },
    }
    nginx = ("podiumd", "openzaak-1", "nginx")
    assert resource_limits([pod], "memory", quantity_bytes) == {KEY: 1024**3, nginx: None}
    assert resource_limits([pod], "cpu", quantity_cores) == {KEY: 0.5, nginx: None}


def watch(**fields):
    found = Watch(frozenset(("openzaak", "zac")), LIMITS, started=at(0), ended=at(60))
    for name, value in fields.items():
        setattr(found, name, value)
    return found


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        ({KEY: 1.0, ("podiumd", "openzaak-2", "openzaak"): 0.5}, "180/s for the 1.5 vCPU of openzaak's CPU limits"),
        ({KEY: None}, "openzaak has no CPU limit"),
        ({("podiumd", "zac-1", "zac"): 1.0}, "openzaak has no CPU limit"),
    ],
)
def test_capacity_of_the_cpu_limits_per_vcpu(limits, expected):
    measured = EndpointStats(requests=12, failures=0, p95_ms=67, per_second=0.2)
    line = capacity(watch(cpu_limits=limits), "openzaak", 120, measured)
    assert line.startswith("0.2/s at p95 67 ms; reference 120/s per vCPU")
    assert line.endswith(expected)


def test_problems_name_restarts_unready_pods_unavailability_and_memory():
    restart = Disruption("2026-11-14T10:00:30Z", "container openzaak-1/openzaak restarted 1x (last: OOMKilled at x)")
    found = watch(
        disruptions=[restart],
        unready=["zac-1/zac: not ready"],
        samples=[Sample(at(0), "zac", None), Sample(at(5), "zac", "HTTP 503")],
        rss_series={KEY: [(at(0), 900 * MIB), (at(5), 950 * MIB)]},
        working_set={KEY: 990 * MIB},
        memory_limits={KEY: 1000 * MIB},
    )
    assert problems(found) == [
        "container openzaak-1/openzaak restarted 1x (last: OOMKilled at x) during the load",
        "zac-1/zac: not ready not Ready 1s after the load",
        "zac root healthy in 1 of 2 samples < 90%",
        "openzaak-1/openzaak peak RSS 950 MiB = 95% of its limit > 90%",
    ]


QUIET_REPORT = """Load 10:00:00-10:01:00 UTC; Ready again 2 s after it.

| Component | Healthy root answers | Highest RSS share of a memory limit | Largest working set |
|---|---|---|---|
| openzaak | 1/1 | 50% (openzaak-1/openzaak) | 1000 MiB (openzaak-1/openzaak) |
| zac | 1/1 | - | 300 MiB (zac-1/zac, no limit) |

No failed requests, failing root answers or pod changes.

No memory limit: zac-1/zac.

Not measured: CPU throttling: kubelet cAdvisor metrics unreadable: forbidden."""


def test_a_quiet_load_has_no_problems_and_says_so():
    found = watch(
        samples=[Sample(at(0), "zac", None), Sample(at(0), "openzaak", None)],
        rss_series={KEY: [(at(0), 512 * MIB)], ("podiumd", "zac-1", "zac"): [(at(0), 200 * MIB)]},
        # Page cache near the limit, as Elasticsearch has: no problem.
        working_set={KEY: 1000 * MIB, ("podiumd", "zac-1", "zac"): 300 * MIB},
        memory_limits={KEY: 1024 * MIB, ("podiumd", "zac-1", "zac"): None},
        recovered_s=2.0,
        throttled={KEY: 0.004},
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
container_memory_rss{container="openzaak",namespace="podiumd",pod="openzaak-1"} 2e+08 1
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
    with watched(env, env.profile.urls, ["openzaak", "zac"], LIMITS) as found:
        assert found.components == frozenset(("openzaak",))  # zac has no URL in the profile
    assert found.samples
    assert {sample.problem for sample in found.samples} == {None}
    assert found.rss == {KEY: 2e8}
    assert found.working_set == {KEY: 3e8}
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
    with watched(env, env.profile.urls, ["openzaak"], LIMITS) as found:
        assert found.components == frozenset(("openzaak",))
    assert {sample.problem for sample in found.samples} == {"HTTP 503"}
    assert found.notes == ["pods, restarts and memory: the environment has no cluster access"]
    assert problems(found) == [f"openzaak root healthy in 0 of {len(found.samples)} samples < 90%"]


def test_watched_run_watches_the_command_with_the_limits_of_perf_yaml(env_factory, fake_http):
    fake_http({"/": (200, {})})
    env = env_factory()
    env.capabilities = Capabilities(frozenset(("openzaak",)), {"cluster": "kubectl failed"})
    found = watched_run(env, env.profile.urls, ["openzaak"], [sys.executable, "-c", "pass"], timeout=60)
    assert found.limits == availability_limits(REPO_ROOT / "perf.yaml")
    assert found.ended >= found.started


def readings(*mib: float) -> Series:
    """RSS readings a minute apart from at(0), in MiB."""
    return [(float(at(60 * minute)), value * MIB) for minute, value in enumerate(mib)]


LEAKING: ContainerKey = ("podiumd", "openklant-1", "openklant")
# 2 MiB/min for 15 minutes.
LEAK = readings(*range(100, 132, 2))
# 3 MiB/min for 10 minutes, then flat.
LEVELLING = readings(*(100 + 3 * min(minute, 10) for minute in range(16)))
# 100 MiB/min for 5 minutes, then flat.
WARMING = readings(*(min(100 * (minute + 1), 600) for minute in range(16)))


def test_growth_per_min_is_the_least_squares_slope():
    assert growth_per_min(LEAK) == pytest.approx(2)
    # A sawtooth, as uWSGI max-requests makes it: well below 1 MiB/min.
    assert growth_per_min(readings(100, 104, 100, 104, 100, 104)) == pytest.approx(6 / 17.5)


def test_memory_trend_leaves_out_the_warm_up():
    trend = memory_trend(WARMING, at(0), warmup_s=300)
    assert trend == Trend(first=100, last=600, peak=600, steps=(100, 600, 600, 600), growth=0, late_growth=0)


def test_memory_trend_needs_readings_that_span_the_warm_up_after_it():
    assert memory_trend(LEAK[:10], at(0), warmup_s=300) is None  # 4 minutes after the warm-up
    assert memory_trend(LEAK[:3], at(0), warmup_s=0) is None  # too few readings
    assert memory_trend(LEAK[:10], at(0), warmup_s=0) is not None
    # A gap: one reading in the last half of the time after the warm-up.
    assert memory_trend([*LEAK[:4], LEAK[-1]], at(0), warmup_s=0) is None


def test_memory_trend_of_a_container_that_started_later_warms_up_from_its_first_reading():
    started_later = [(second + 300, value) for second, value in WARMING]
    trend = memory_trend(started_later, at(0), warmup_s=300)
    assert trend is not None
    assert trend.growth == 0


def test_watched_keeps_sampling_memory_after_an_unreadable_reading(env_factory, fake_runner, fake_http):
    fake_runner.answers = {
        "get pods": (0, json.dumps({"items": [cluster_pod("openzaak-1")]})),
        "get nodes": (0, json.dumps({"items": [{"metadata": {"name": "n1"}}]})),
        "get --raw": (1, "forbidden"),
    }
    fake_http({"/": (200, {})})
    env = env_factory()
    env.capabilities = Capabilities(frozenset(("cluster", "openzaak")), {})
    with watched(env, env.profile.urls, ["openzaak"], LIMITS) as found:
        wait_until(lambda: sum("--raw" in call for call in fake_runner.calls) > 3, timeout=5, description="readings")
    memory = [note for note in found.notes if note.startswith("memory:")]
    assert len(memory) == 1
    assert memory[0].endswith("cadvisor: forbidden")


def test_problems_flag_rss_that_keeps_growing_but_not_rss_that_levels_off():
    found = watch(rss_series={LEAKING: LEAK, KEY: LEVELLING})
    trends = memory_trends(found)
    assert trends[KEY].growth > 1
    assert trends[KEY].late_growth == pytest.approx(0)
    assert problems(found) == [
        "openklant-1/openklant RSS keeps growing: 2.0 MiB/min after the warm-up, 2.0 in its last half > 1"
    ]
    lines = report(found, HEADER).splitlines()
    table = lines.index("| Container | Start | End | Peak | Growth MiB/min | In its last half | Every 5 min |")
    assert lines[table - 2] == "RSS in MiB; growth after a warm-up of 300 s, least squares."
    assert lines[table + 2] == "| openklant-1/openklant | 100 | 130 | 130 | +2.00 | +2.00 | 100 110 120 130 |"
    assert lines[table + 3].startswith("| openzaak-1/openzaak | 100 | 130 | 130 | +1.")
