"""Response times under load: TA's k6 api-perf.js reads, plus writes and the users' searches, in Locust.

One Locust run (src/podiumd_tests/perf/locustfile.py, headless, --perf-users users for
--perf-duration) serves every test; each endpoint must meet its p95 and failure-ratio threshold
from perf.yaml, and may not have slowed down (stats.slowdown_limit) against the environment's
earlier runs with the same settings (users, duration, calls, volume data). The components it loads
must stay available (podiumd_tests.perf.availability). Locust's stats and the
settings go to the run's perf/ directory; without a run directory (plain pytest) there is no history.
"""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.perf.availability import Watch
from podiumd_tests.perf.availability import availability_limits
from podiumd_tests.perf.availability import watched
from podiumd_tests.perf.availability_report import capacity
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.perf.availability_report import report
from podiumd_tests.perf.runs import ENDPOINTS
from podiumd_tests.perf.runs import KEYCLOAK_PER_VCPU
from podiumd_tests.perf.runs import api_user_steps
from podiumd_tests.perf.runs import locust_command
from podiumd_tests.perf.stats import HISTORY
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
    from pathlib import Path

    from _pytest.mark import ParameterSet

    from podiumd_tests.environment import Environment
    from podiumd_tests.perf.stats import EndpointStats

pytestmark = pytest.mark.perf

LOCUSTFILE = REPO_ROOT / "src" / "podiumd_tests" / "perf" / "locustfile.py"


@pytest.fixture(scope="module", name="load")
def fixture_load(
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    urls: dict[str, str],
    need_bootstrap: Callable[..., None],
    perf_dir: Path,
    run_tag: str,
) -> tuple[dict[str, EndpointStats], Watch]:
    """The stats of one Locust run against the environment, and the availability of the components it loads."""
    need_bootstrap(*api_user_steps(podiumd_env))
    directory = perf_dir
    users = str(request.config.getoption("--perf-users"))
    duration = str(request.config.getoption("--perf-duration"))
    # Runs compare only with runs of the same load, calls and volume data (seed-volume).
    calls = sorted(e for e, c in ENDPOINTS.items() if c in podiumd_env.profile.urls)
    settings = {"users": users, "duration": duration, "calls": calls, "volume": counts(podiumd_env)}
    (directory / SETTINGS).write_text(f"{json.dumps(settings, sort_keys=True)}\n", encoding="utf-8")
    command = locust_command(LOCUSTFILE, users, duration, directory / "locust", podiumd_env.profile.name, urls=urls)
    # Users finish their round, so every write is deleted.
    command += ["--stop-timeout", "60", "--podiumd-run-tag", run_tag, "ApiUser"]
    with watched(podiumd_env, urls, ENDPOINTS.values(), availability_limits(REPO_ROOT / "perf.yaml")) as watch:
        run_checked(run_process, command, timeout=600)
    return read_stats((directory / STATS).read_text(encoding="utf-8")), watch


@pytest.fixture(scope="module", name="stats")
def fixture_stats(load: tuple[dict[str, EndpointStats], Watch]) -> dict[str, EndpointStats]:
    """The stats of the Locust run."""
    return load[0]


TA_K6 = pytest.mark.source(
    "TA perf/api-perf.js",
    "API performance with k6: read-only traffic per API group, with p95/p99 response times per API.",
)
OZ_BENCHMARK = pytest.mark.source(
    "upstream open-zaak/open-zaak performance_test/",
    "Open Zaak's own benchmark: documents and zaken lists at a deep page, also for a client with few zaaktypen.",
)
MADE_HERE = pytest.mark.source(
    "podiumd-tests", "Writes and the searches users type in ZAC, KISS and the portal, under the same load."
)
KC_BENCHMARK = pytest.mark.source(
    "upstream keycloak/keycloak-benchmark scenarios authentication.AuthorizationCode and ClientSecret",
    "Keycloak's password logins and client-credentials grants, against its sizing guide's rates per vCPU.",
)
ZAC_LOAD = pytest.mark.source(
    "upstream infonl/dimpact-zaakafhandelcomponent scripts/test-data/create-load.py",
    "ZAC's own load script: zaken started in ZAC and documents uploaded to them.",
)
SOURCES = {
    **dict.fromkeys(("oz_zaken", "oz_zaaktypen", "ok2_partijen", "brp_persoon", "kc_discovery"), TA_K6),
    **dict.fromkeys(("oz_documenten_ordered", "oz_zaken_one_zaaktype"), OZ_BENCHMARK),
    **dict.fromkeys(KEYCLOAK_PER_VCPU, KC_BENCHMARK),
    **dict.fromkeys(("zac_zaak_create", "zac_document_upload"), ZAC_LOAD),
}


def endpoint_params() -> list[ParameterSet]:
    """One param per endpoint, requiring its component and naming its source."""
    params = [requiring(c, e, test_id=e) for e, c in ENDPOINTS.items()]
    return [
        pytest.param(*p.values, id=p.id, marks=[*p.marks, SOURCES.get(e, MADE_HERE)])
        for p, e in zip(params, ENDPOINTS, strict=True)
    ]


@pytest.mark.parametrize("endpoint", endpoint_params())
@pytest.mark.scenario("""
    Given simulated users call each API endpoint during a load test
    When the load test ends
    Then the endpoint's 95th percentile response time stays within its threshold
    And so does its ratio of failed requests
""")
def test_endpoint_meets_its_threshold(
    load: tuple[dict[str, EndpointStats], Watch], record_property: Callable[[str, object], None], endpoint: str
) -> None:
    """The endpoint's p95 and failure ratio stay within perf.yaml; Keycloak's against its sizing guide in the report."""
    stats, watch = load
    assert endpoint in stats, f"Locust made no {endpoint} requests"
    if endpoint in KEYCLOAK_PER_VCPU:
        record_property("report", capacity(watch, "keycloak", KEYCLOAK_PER_VCPU[endpoint], stats[endpoint]))
    assert violations(stats[endpoint], thresholds(REPO_ROOT / "perf.yaml", endpoint)) == []


@pytest.mark.source(
    "podiumd-tests",
    "Perf shows change over time per environment, also where its absolute numbers mean little (minikube).",
)
@pytest.mark.parametrize("endpoint", [requiring(c, e, test_id=e) for e, c in ENDPOINTS.items()])
@pytest.mark.scenario("""
    Given earlier load tests of this environment with the same settings
    When each API endpoint is measured in a new load test
    Then its 95th percentile response time is no slowdown against the median of the earlier runs
""")
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


@pytest.mark.source(
    "podiumd-tests",
    "Load must not take a component down: Open Klant #636 and Open Zaak #1837 grew memory under load until restarted.",
)
@pytest.mark.scenario("""
    Given simulated users call the API endpoints during a load test
    When the load test ends
    Then no pod of a loaded component restarted or was replaced
    And their pods are ready again within the recovery time
    And each loaded component answered its health check in nearly all samples during the load
    And no container's memory came close to its limit
""")
def test_loaded_components_stay_available(
    load: tuple[dict[str, EndpointStats], Watch], perf_dir: Path, record_property: Callable[[str, object], None]
) -> None:
    """The loaded components stay within perf.yaml's availability limits; the timeline goes to summary.md."""
    watch = load[1]
    record_property("report", report(watch, (perf_dir / HISTORY).read_text(encoding="utf-8")))
    assert problems(watch) == []
