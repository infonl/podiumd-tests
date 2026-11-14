"""A soak: SOAK_MIX's calls by --perf-users users for --perf-soak, such as 60m; opt-in.

The report shows each container's RSS over the run and its growth after the warm-up. The test fails when a
container's RSS keeps growing or the loaded components do not stay available (perf.yaml `availability`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.perf.availability import watched_run
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.perf.availability_report import report
from podiumd_tests.perf.runs import ENDPOINTS
from podiumd_tests.perf.runs import SOAK_MIX
from podiumd_tests.perf.runs import api_user_steps
from podiumd_tests.perf.runs import locust_command
from podiumd_tests.perf.runs import mix_arguments
from podiumd_tests.perf.stats import HISTORY
from podiumd_tests.perf.stats import locust_csv
from podiumd_tests.wait import parse_duration

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.perf,
    pytest.mark.source(
        "upstream maykinmedia/open-klant issue 636",
        "Open Klant 2.17.1 grew from 291 MiB to 1.1 GiB in 22 klantcontacten lists with expand; Open Zaak #1837 alike.",
    ),
]

LOCUSTFILE = REPO_ROOT / "src" / "podiumd_tests" / "perf" / "locustfile.py"
PREFIX = "soak"


@pytest.mark.scenario("""
    Given a few simulated users list zaken and klantcontacten with their related objects, write, search and log in
    When they keep doing so at a steady pace for a long time
    Then no container's memory keeps growing after the warm-up
    And no pod of a loaded component restarted or was replaced
    And their pods are ready again within the recovery time
    And each loaded component answered its health check in nearly all samples during the load
""")
def test_soak_memory_levels_off(
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    urls: dict[str, str],
    need_bootstrap: Callable[..., None],
    perf_dir: Path,
    run_tag: str,
    record_property: Callable[[str, object], None],
) -> None:
    """No container's RSS keeps growing over the soak; the loaded components stay within perf.yaml's `availability`."""
    soak = request.config.getoption("--perf-soak")
    if not soak:
        pytest.skip("no soak: pass --perf-soak, e.g. --perf-soak 60m")
    need_bootstrap(*api_user_steps(podiumd_env))
    seconds = int(parse_duration(str(soak)).total_seconds())
    users = str(request.config.getoption("--perf-users"))
    prefix = perf_dir / PREFIX
    command = locust_command(LOCUSTFILE, users, f"{seconds}s", prefix, podiumd_env.profile.name, urls=urls)
    command += [*mix_arguments(SOAK_MIX, urls, run_tag), "ApiUser"]
    watch = watched_run(podiumd_env, urls, ENDPOINTS.values(), command, timeout=seconds + 600)
    record_property("report", report(watch, locust_csv(prefix, HISTORY).read_text(encoding="utf-8")))
    assert problems(watch) == []
