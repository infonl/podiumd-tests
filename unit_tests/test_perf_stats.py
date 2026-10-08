"""Unit tests for reading Locust's stats and checking them against perf.yaml."""

from podiumd_tests.perf.stats import SETTINGS
from podiumd_tests.perf.stats import STATS
from podiumd_tests.perf.stats import EndpointStats
from podiumd_tests.perf.stats import Threshold
from podiumd_tests.perf.stats import baseline_p95
from podiumd_tests.perf.stats import earlier_stats
from podiumd_tests.perf.stats import read_stats
from podiumd_tests.perf.stats import thresholds
from podiumd_tests.perf.stats import violations

CSV = """Type,Name,Request Count,Failure Count,95%
API,oz_zaken,100,2,1600
,Aggregated,100,2,1600
"""


def test_read_stats_skips_the_aggregated_row():
    assert read_stats(CSV) == {"oz_zaken": EndpointStats(requests=100, failures=2, p95_ms=1600.0)}


def test_endpoint_entry_overrides_the_defaults(tmp_path):
    perf = tmp_path / "perf.yaml"
    perf.write_text(
        "defaults: {p95_ms: 1500, max_failure_ratio: 0.01, max_slowdown: 1.5}\nendpoints: {oz_zaken: {p95_ms: 2000}}\n"
    )
    assert thresholds(perf, "oz_zaken") == Threshold(p95_ms=2000.0, max_failure_ratio=0.01, max_slowdown=1.5)
    assert thresholds(perf, "kc_discovery") == Threshold(p95_ms=1500.0, max_failure_ratio=0.01, max_slowdown=1.5)


def test_violations_name_each_exceeded_limit():
    stats = read_stats(CSV)["oz_zaken"]
    assert violations(stats, Threshold(1500, 0.01, 1.5)) == ["p95 1600 ms > 1500 ms", "2/100 failed > 1%"]
    assert violations(stats, Threshold(2000, 0.05, 1.5)) == []
    assert violations(EndpointStats(0, 0, 0.0), Threshold(2000, 0.05, 1.5)) == ["no requests"]


def perf_run(root, name, p95, settings='{"users": "5"}'):
    perf = root / name[:7].replace("2026", "2026-") / name / "perf"
    perf.mkdir(parents=True)
    (perf / STATS).write_text(f"Type,Name,Request Count,Failure Count,95%\nAPI,oz_zaken,10,0,{p95}\n")
    (perf / SETTINGS).write_text(settings)
    return perf.parent


def test_earlier_stats_take_only_older_runs_of_the_env_with_the_same_settings(tmp_path):
    perf_run(tmp_path, "20261001-100000_kees00_perf_a", 100)
    perf_run(tmp_path, "20261002-100000_minikube_perf_b", 200, settings='{"users": "10"}')
    perf_run(tmp_path, "20261003-100000_minikube_perf_c", 300)
    current = perf_run(tmp_path, "20261004-100000_minikube_perf_d", 999)
    perf_run(tmp_path, "20261005-100000_minikube_perf_e", 500)
    history = earlier_stats(current)
    assert [h["oz_zaken"].p95_ms for h in history] == [300.0]
    assert baseline_p95(history, "oz_zaken") is None  # one earlier run is no baseline
    assert baseline_p95([*history, *history, *history], "oz_zaken") == 300.0
    assert baseline_p95([*history, *history, *history], "kc_discovery") is None
