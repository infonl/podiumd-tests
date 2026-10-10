"""API response times under load: TA's k6 api-perf.js, ported to Locust.

One Locust run (src/podiumd_tests/perf/locustfile.py, headless, --perf-users users for
--perf-duration) serves every test; each endpoint must meet its p95 and failure-ratio threshold
from perf.yaml, and may not have slowed down more than max_slowdown against the environment's
earlier runs with the same settings (users, duration, volume data). Locust's stats and the settings go to the run's perf/
directory; without a run directory (plain pytest) there is no history to compare with.
"""

from __future__ import annotations

import json
import sys

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.perf import ENDPOINTS
from podiumd_tests.perf.stats import SETTINGS
from podiumd_tests.perf.stats import STATS
from podiumd_tests.perf.stats import baseline_p95
from podiumd_tests.perf.stats import earlier_stats
from podiumd_tests.perf.stats import read_stats
from podiumd_tests.perf.stats import slowdown_limit
from podiumd_tests.perf.stats import thresholds
from podiumd_tests.perf.stats import violations
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.seed.volume import counts

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.environment import Environment
    from podiumd_tests.perf.stats import EndpointStats

pytestmark = pytest.mark.perf

LOCUSTFILE = REPO_ROOT / "src" / "podiumd_tests" / "perf" / "locustfile.py"


@pytest.fixture(scope="module", name="perf_dir")
def fixture_perf_dir(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The run's perf/ directory, or a temporary one outside a CLI run."""
    junit = request.config.option.xmlpath
    directory = Path(junit).parent / "perf" if junit else tmp_path_factory.mktemp("perf")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.fixture(scope="module", name="stats")
def fixture_stats(
    request: pytest.FixtureRequest, podiumd_env: Environment, need_bootstrap: Callable[..., None], perf_dir: Path
) -> dict[str, EndpointStats]:
    """The stats of one Locust run against the environment."""
    need_bootstrap("openzaak-client", "openklant-token")
    directory = perf_dir
    users = str(request.config.getoption("--perf-users"))
    duration = str(request.config.getoption("--perf-duration"))
    # Runs compare only with runs of the same load and volume data (seed-volume).
    settings = {"users": users, "duration": duration, "volume": counts(podiumd_env)}
    (directory / SETTINGS).write_text(json.dumps(settings, sort_keys=True) + "\n", encoding="utf-8")
    command = [sys.executable, "-m", "locust", "-f", str(LOCUSTFILE), "--headless", "--only-summary"]
    command += ["--users", users, "--spawn-rate", users, "--run-time", duration, "--exit-code-on-error", "0"]
    command += ["--csv", str(directory / "locust"), "--podiumd-env", podiumd_env.profile.name]
    run_checked(run_process, command, timeout=600)
    return read_stats((directory / STATS).read_text(encoding="utf-8"))


@pytest.mark.parametrize("endpoint", [requiring(c, e, test_id=e) for e, c in ENDPOINTS.items()])
def test_endpoint_meets_its_threshold(stats: dict[str, EndpointStats], endpoint: str) -> None:
    """The endpoint's p95 and failure ratio stay within perf.yaml (TA perf/api-perf.js)."""
    assert endpoint in stats, f"Locust made no {endpoint} requests"
    assert violations(stats[endpoint], thresholds(REPO_ROOT / "perf.yaml", endpoint)) == []


@pytest.mark.parametrize("endpoint", [requiring(c, e, test_id=e) for e, c in ENDPOINTS.items()])
def test_endpoint_is_not_slower_than_before(stats: dict[str, EndpointStats], perf_dir: Path, endpoint: str) -> None:
    """The endpoint's p95 is no slowdown (stats.slowdown_limit) against its median over the earlier comparable runs."""
    if endpoint not in stats:
        pytest.skip(f"Locust made no {endpoint} requests")
    baseline = baseline_p95(earlier_stats(perf_dir.parent), endpoint) if perf_dir.parent.name.count("_") >= 3 else None
    if baseline is None:
        pytest.skip(f"no earlier perf run of this environment with the same settings has {endpoint}")
    limit = slowdown_limit(thresholds(REPO_ROOT / "perf.yaml", endpoint), baseline)
    assert stats[endpoint].p95_ms <= limit, (
        f"p95 {stats[endpoint].p95_ms:.0f} ms > {limit:.0f} ms (baseline {baseline:.0f} ms)"
    )
