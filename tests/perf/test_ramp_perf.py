"""A ramp: RAMP_MIX's calls at the --perf-ramp user counts, each step --perf-duration long; opt-in.

The report names the knee: the users at which an endpoint first exceeds its perf.yaml threshold. The test fails only
when the loaded components do not stay available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.perf.availability import availability_limits
from podiumd_tests.perf.availability import watched
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.perf.availability_report import report
from podiumd_tests.perf.runs import ENDPOINTS
from podiumd_tests.perf.runs import RAMP_MIX
from podiumd_tests.perf.runs import api_user_steps
from podiumd_tests.perf.runs import locust_command
from podiumd_tests.perf.runs import ramp_steps
from podiumd_tests.perf.stats import HISTORY
from podiumd_tests.perf.stats import STATS
from podiumd_tests.perf.stats import by_label
from podiumd_tests.perf.stats import locust_csv
from podiumd_tests.perf.stats import ramp_report
from podiumd_tests.perf.stats import read_stats
from podiumd_tests.perf.stats import thresholds
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process
from podiumd_tests.wait import parse_duration

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.perf,
    pytest.mark.source(
        "podiumd-tests", "The load at which response times or failures pass their thresholds, for capacity planning."
    ),
]

LOCUSTFILE = REPO_ROOT / "src" / "podiumd_tests" / "perf" / "ramp_locustfile.py"
PREFIX = "ramp"


@pytest.mark.scenario("""
    Given simulated users log in, start zaken, upload documents, search and read
    When their number steps up, each step for the same time
    Then the report names the number of users at which a call first passes its threshold
    And the components they load stay available: no restart, ready again and healthy during the load
""")
def test_ramp_finds_the_knee(
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    urls: dict[str, str],
    need_bootstrap: Callable[..., None],
    perf_dir: Path,
    run_tag: str,
    record_property: Callable[[str, object], None],
) -> None:
    """The ramp's steps and knee go to the report; the loaded components stay within perf.yaml's `availability`."""
    ramp = request.config.getoption("--perf-ramp")
    if not ramp:
        pytest.skip("no ramp: pass --perf-ramp, e.g. --perf-ramp 2,4,8,16")
    need_bootstrap(*api_user_steps(podiumd_env))
    steps = ramp_steps(str(ramp))
    step_s = parse_duration(str(request.config.getoption("--perf-duration"))).total_seconds()
    mix = [call for call in RAMP_MIX if ENDPOINTS[call] in urls]
    prefix = perf_dir / PREFIX
    run_time = f"{int(step_s * len(steps))}s"
    command = locust_command(LOCUSTFILE, str(steps[0]), run_time, prefix, podiumd_env.profile.name, urls=urls)
    command += ["--stop-timeout", "60", "--podiumd-run-tag", run_tag, "--podiumd-calls", ",".join(mix)]
    command += ["--podiumd-steps", str(ramp), "--podiumd-step-time", str(step_s)]
    limits = availability_limits(REPO_ROOT / "perf.yaml")
    with watched(podiumd_env, urls, ENDPOINTS.values(), limits) as watch:
        run_checked(run_process, command, timeout=int(step_s * len(steps)) + 600)
    stats = by_label(read_stats(locust_csv(prefix, STATS).read_text(encoding="utf-8")))
    knee = ramp_report(stats, lambda endpoint: thresholds(REPO_ROOT / "perf.yaml", endpoint))
    record_property("report", f"{knee}\n\n{report(watch, locust_csv(prefix, HISTORY).read_text(encoding='utf-8'))}")
    assert problems(watch) == []
