"""API response times under load: TA's k6 api-perf.js, ported to Locust.

One Locust run (src/podiumd_tests/perf/locustfile.py, headless, --perf-users users for
--perf-duration) serves every test; each endpoint must meet its p95 and failure-ratio threshold
from perf.yaml. Locust's stats go to the run's perf/ directory.
"""

from __future__ import annotations

import sys

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.perf import ENDPOINTS
from podiumd_tests.perf.stats import read_stats
from podiumd_tests.perf.stats import thresholds
from podiumd_tests.perf.stats import violations
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process
from podiumd_tests.pytest_plugin import requiring

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.environment import Environment
    from podiumd_tests.perf.stats import EndpointStats

pytestmark = pytest.mark.perf

LOCUSTFILE = REPO_ROOT / "src" / "podiumd_tests" / "perf" / "locustfile.py"


@pytest.fixture(scope="module", name="stats")
def fixture_stats(
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, EndpointStats]:
    """The stats of one Locust run against the environment."""
    need_bootstrap("openzaak-client", "openklant-token")
    junit = request.config.option.xmlpath
    directory = Path(junit).parent / "perf" if junit else tmp_path_factory.mktemp("perf")
    directory.mkdir(parents=True, exist_ok=True)
    users = str(request.config.getoption("--perf-users"))
    duration = str(request.config.getoption("--perf-duration"))
    command = [sys.executable, "-m", "locust", "-f", str(LOCUSTFILE), "--headless", "--only-summary"]
    command += ["--users", users, "--spawn-rate", users, "--run-time", duration, "--exit-code-on-error", "0"]
    command += ["--csv", str(directory / "locust"), "--podiumd-env", podiumd_env.profile.name]
    run_checked(run_process, command, timeout=600)
    return read_stats((directory / "locust_stats.csv").read_text(encoding="utf-8"))


@pytest.mark.parametrize("endpoint", [requiring(c, e, test_id=e) for e, c in ENDPOINTS.items()])
def test_endpoint_meets_its_threshold(stats: dict[str, EndpointStats], endpoint: str) -> None:
    """The endpoint's p95 and failure ratio stay within perf.yaml (TA perf/api-perf.js)."""
    assert endpoint in stats, f"Locust made no {endpoint} requests"
    assert violations(stats[endpoint], thresholds(REPO_ROOT / "perf.yaml", endpoint)) == []
