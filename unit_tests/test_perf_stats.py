"""Unit tests for reading Locust's stats and checking them against perf.yaml."""

from podiumd_tests.perf import runs
from podiumd_tests.perf.runs import locust_command
from podiumd_tests.perf.runs import locust_environment
from podiumd_tests.perf.stats import FAILURES
from podiumd_tests.perf.stats import SETTINGS
from podiumd_tests.perf.stats import STATS
from podiumd_tests.perf.stats import EndpointStats
from podiumd_tests.perf.stats import Threshold
from podiumd_tests.perf.stats import baseline_p95
from podiumd_tests.perf.stats import by_label
from podiumd_tests.perf.stats import earlier_stats
from podiumd_tests.perf.stats import labelled
from podiumd_tests.perf.stats import locust_csv
from podiumd_tests.perf.stats import read_failures
from podiumd_tests.perf.stats import read_stats
from podiumd_tests.perf.stats import slowdown_limit
from podiumd_tests.perf.stats import summed
from podiumd_tests.perf.stats import thresholds
from podiumd_tests.perf.stats import violations

CSV = """Type,Name,Request Count,Failure Count,95%,Requests/s
API,oz_zaken,100,2,1600,1.5
,Aggregated,100,2,1600,1.5
"""


def test_read_stats_skips_the_aggregated_row():
    assert read_stats(CSV) == {"oz_zaken": EndpointStats(requests=100, failures=2, p95_ms=1600.0, per_second=1.5)}


def test_endpoint_entry_overrides_the_defaults(tmp_path):
    perf = tmp_path / "perf.yaml"
    perf.write_text(
        "defaults: {p95_ms: 1500, max_failure_ratio: 0.01, max_slowdown: 1.5, min_slowdown_ms: 200}\nendpoints: {oz_zaken: {p95_ms: 2000}}\n"
    )
    assert thresholds(perf, "oz_zaken") == Threshold(
        p95_ms=2000.0, max_failure_ratio=0.01, max_slowdown=1.5, min_slowdown_ms=200.0
    )
    assert thresholds(perf, "kc_discovery") == Threshold(
        p95_ms=1500.0, max_failure_ratio=0.01, max_slowdown=1.5, min_slowdown_ms=200.0
    )


def test_violations_name_each_exceeded_limit():
    stats = read_stats(CSV)["oz_zaken"]
    assert violations(stats, Threshold(1500, 0.01, 1.5, 200)) == ["p95 1600 ms > 1500 ms", "2/100 failed > 1%"]
    assert violations(stats, Threshold(2000, 0.05, 1.5, 200)) == []
    assert violations(EndpointStats(0, 0, 0), Threshold(2000, 0.05, 1.5, 200)) == ["no requests"]


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
    assert baseline_p95([*history, *history, *history], "oz_zaken") == 300
    assert baseline_p95([*history, *history, *history], "kc_discovery") is None


def test_a_slowdown_must_pass_both_the_ratio_and_the_margin():
    threshold = Threshold(1500, 0.01, 1.5, 200)
    assert slowdown_limit(threshold, 130) == 330  # small numbers: the margin
    assert slowdown_limit(threshold, 1000) == 1500  # large numbers: the ratio


def test_locust_command_runs_headless_against_the_environment(tmp_path):
    urls = {"api-proxy": "http://127.0.0.1:4711"}
    command = locust_command(tmp_path / "lf.py", "10", "150s", tmp_path / "out", "ontw-dim1", urls=urls)
    assert command[1:5] == ["-m", "locust", "-f", str(tmp_path / "lf.py")]
    assert command[command.index("--users") + 1] == command[command.index("--spawn-rate") + 1] == "10"
    assert command[-7:-4] == ["--csv", str(tmp_path / "out"), "--csv-full-history"]
    assert command[-4:] == ["--podiumd-env", "ontw-dim1", "--podiumd-urls", '{"api-proxy": "http://127.0.0.1:4711"}']


def test_locust_environment_reaches_components_at_the_given_urls(monkeypatch, profile_factory):
    monkeypatch.setattr(runs, "load_profile", lambda _name, _envs: profile_factory())
    env = locust_environment("test-env", '{"openzaak": "http://127.0.0.1:4711"}')
    assert env.profile.urls["openzaak"] == "http://127.0.0.1:4711"
    assert env.profile.urls["keycloak-admin"] == "https://kc-admin.example.test"


def test_labelled_stats_group_by_number_and_endpoint():
    stats = read_stats(
        "Type,Name,Request Count,Failure Count,95%\n"
        f"API,{labelled('oz_hot', 100)},100,3,900\nAPI,{labelled('oz_hot', 0)},100,0,300\n"
        f"API,{labelled('zac_search', 4)},10,0,50\nAPI,kc_discovery,5,0,20\n"
    )
    assert by_label(stats) == {
        0: {"oz_hot": EndpointStats(100, 0, 300)},
        4: {"zac_search": EndpointStats(10, 0, 50)},
        100: {"oz_hot": EndpointStats(100, 3, 900)},
    }


def test_summed_stats_add_up_and_keep_the_highest_p95():
    assert summed([EndpointStats(100, 0, 300, 2), EndpointStats(100, 3, 900, 1)]) == EndpointStats(200, 3, 900, 3)
    assert summed([]) == EndpointStats(0, 0, 0)


def test_read_failures_puts_the_most_frequent_first():
    text = "Method,Name,Error,Occurrences\nAPI,a,HTTP 503,2\nAPI,a,HTTP 500,7\n"
    assert read_failures(text) == [("a", "HTTP 500", 7), ("a", "HTTP 503", 2)]


def test_locust_csv_follows_the_csv_prefix(tmp_path):
    assert locust_csv(tmp_path / "hot-zaak", FAILURES) == tmp_path / "hot-zaak_failures.csv"
