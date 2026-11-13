"""Gateway response times: anonymous scenarios through the public gateway, one Locust run each, run twice.

For comparing gateway settings such as upstream keep-alive: run before and after the change with the same
--perf-users and --perf-duration, and compare the CSVs in the run's perf/gateway/ directory. The second round
shows the noise between runs. Each run warms up for WARMUP before its measured --perf-duration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.perf.availability import availability_limits
from podiumd_tests.perf.availability import watched
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.perf.availability_report import report
from podiumd_tests.perf.runs import GATEWAY_SCENARIOS
from podiumd_tests.perf.runs import locust_command
from podiumd_tests.perf.stats import HISTORY
from podiumd_tests.perf.stats import STATS
from podiumd_tests.perf.stats import read_stats
from podiumd_tests.perf.stats import thresholds
from podiumd_tests.perf.stats import violations
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.wait import parse_duration

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.perf,
    pytest.mark.source("podiumd-tests", "Gateway latency per route under load, for A/B tests of gateway settings."),
]

LOCUSTFILE = REPO_ROOT / "src" / "podiumd_tests" / "perf" / "gateway_locustfile.py"
WARMUP = "30s"
ROUNDS = (1, 2)


@pytest.mark.parametrize(
    ("scenario", "rnd"),
    [requiring(c, s, r, test_id=f"{s}-{r}") for r in ROUNDS for s, (c, _p, _s) in GATEWAY_SCENARIOS.items()],
)
@pytest.mark.scenario("""
    Given simulated anonymous users run each scenario through the public gateway
    When the load test ends after its warm-up and measured time, in each of two rounds
    Then the scenario's 95th percentile response time stays within its threshold
    And so does its ratio of failed requests
    And its component stays available: no restart, ready again and healthy during the load
""")
def test_gateway_scenario_meets_its_threshold(  # fixtures
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    perf_dir: Path,
    record_property: Callable[[str, object], None],
    scenario: str,
    rnd: int,
) -> None:
    """The scenario's p95 and failure ratio stay within perf.yaml's defaults, its component within `availability`."""
    users = str(request.config.getoption("--perf-users"))
    measured = parse_duration(str(request.config.getoption("--perf-duration")))
    warmup = parse_duration(WARMUP).total_seconds()
    run_time = f"{int(warmup + measured.total_seconds())}s"
    prefix = perf_dir / "gateway" / f"{scenario}-{rnd}"
    prefix.parent.mkdir(exist_ok=True)
    command = locust_command(LOCUSTFILE, users, run_time, prefix, podiumd_env.profile.name)
    component = GATEWAY_SCENARIOS[scenario][0]
    with watched(podiumd_env, [component], availability_limits(REPO_ROOT / "perf.yaml")) as watch:
        run_checked(
            run_process, [*command, "--podiumd-scenario", scenario, "--podiumd-warmup", str(warmup)], timeout=900
        )
    history = prefix.with_name(prefix.name + HISTORY.removeprefix("locust")).read_text(encoding="utf-8")
    record_property("report", report(watch, history))
    stats = read_stats(prefix.with_name(prefix.name + STATS.removeprefix("locust")).read_text(encoding="utf-8"))
    assert scenario in stats, f"Locust made no {scenario} requests"
    assert [*violations(stats[scenario], thresholds(REPO_ROOT / "perf.yaml", scenario)), *problems(watch)] == []
