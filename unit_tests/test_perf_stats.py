"""Unit tests for reading Locust's stats and checking them against perf.yaml."""

from podiumd_tests.perf.stats import EndpointStats
from podiumd_tests.perf.stats import Threshold
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
    perf.write_text("defaults: {p95_ms: 1500, max_failure_ratio: 0.01}\nendpoints: {oz_zaken: {p95_ms: 2000}}\n")
    assert thresholds(perf, "oz_zaken") == Threshold(p95_ms=2000.0, max_failure_ratio=0.01)
    assert thresholds(perf, "kc_discovery") == Threshold(p95_ms=1500.0, max_failure_ratio=0.01)


def test_violations_name_each_exceeded_limit():
    stats = read_stats(CSV)["oz_zaken"]
    assert violations(stats, Threshold(1500, 0.01)) == ["p95 1600 ms > 1500 ms", "2/100 failed > 1%"]
    assert violations(stats, Threshold(2000, 0.05)) == []
    assert violations(EndpointStats(0, 0, 0.0), Threshold(2000, 0.05)) == ["no requests"]
