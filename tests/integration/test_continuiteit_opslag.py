"""Continuity when a shared store stops: Redis, the cache and Celery broker of the Maykin apps, and ZAC's Solr.

A module-scoped fixture breaks each store once; each test checks one consequence. The store's operator owns its
StatefulSet; a stop takes the operator down before the StatefulSet and starts it again after.
"""

from __future__ import annotations

import time

from contextlib import contextmanager
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap import names
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.chaos_load import CALM
from podiumd_tests.chaos_load import DELIVERY_TIMEOUT
from podiumd_tests.chaos_load import failures
from podiumd_tests.chaos_load import load_report
from podiumd_tests.chaos_load import recovery_seconds
from podiumd_tests.chaos_load import watched_load
from podiumd_tests.mock_server import Callback
from podiumd_tests.redis import OPERATOR
from podiumd_tests.redis import OWNER_KIND
from podiumd_tests.redis import master_pod
from podiumd_tests.redis import redis_components
from podiumd_tests.redis import redis_deployments
from podiumd_tests.redis import restart_master
from podiumd_tests.responses import is_root_answering
from podiumd_tests.seed.opennotificaties import make_abonnement
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import published_zaaktype
from podiumd_tests.seed.openzaak import zaak_maker
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import ROOT_TIMEOUT
from podiumd_tests.workloads import cluster_state
from podiumd_tests.workloads import disruptions
from podiumd_tests.workloads import operated
from podiumd_tests.workloads import operated_down
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import SOLR_OPERATOR
from podiumd_tests.zac import SOLR_OWNER_KIND
from podiumd_tests.zac import is_zaak_listed
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import search_failure

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator
    from collections.abc import Iterator

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.workloads import Disruption

pytestmark = [
    pytest.mark.integration,
    pytest.mark.destructive,
    pytest.mark.slow,
    pytest.mark.requires("cluster"),
]

# A deleted Redis pod is replaced and the operator labels it master.
REDIS_RECOVERY = 300
# Seconds of load after Redis is back: a Celery worker stuck since the restart fails its liveness probe 3 x 50 s.
REDIS_AFTERMATH = 180
# Seconds ZAC's Solr stays stopped: longer than ZAC's readiness probe tolerates a failing check (20 x 10 s).
SOLR_OUTAGE = 240
# The time Solr's nodes get to be ready again.
SOLR_RESTORE_TIMEOUT = 600


@dataclass(frozen=True)
class Outage:
    """What one outage did: the failed calls, the restarts besides the stopped store, and the report."""

    failed: list[str]
    restarted: list[Disruption]
    report: str
    measured: dict[str, object]


@dataclass(frozen=True)
class RedisRestart(Outage):
    """What a Redis restart under load did to Open Zaak, its subscriber and Redis's users."""

    lost: list[str]
    created: int
    silent: list[str]
    recovered: float | None


@dataclass(frozen=True)
class SolrOutage(Outage):
    """What stopping ZAC's Solr did to ZAC's zaak page, its search and the indexing of a new zaak."""

    search: str | None
    found: bool


@contextmanager
def own_registry(request: pytest.FixtureRequest, run_tag: str) -> Generator[ResourceRegistry]:
    """Yield a cleanup registry for a module-scoped fixture; its cleanup runs after the module, also on failure."""
    registry = ResourceRegistry(run_tag, keep=bool(request.config.getoption("--keep-data")))
    try:
        yield registry
    finally:
        registry.cleanup()


@pytest.fixture(scope="module", name="redis_restart")
def fixture_redis_restart(  # fixtures
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    urls: dict[str, str],
    http: requests.Session,
    run_tag: str,
    opennotificaties: ApiClient,
    test_zaaktype: JsonObject,
    need_bootstrap: Callable[..., None],
) -> Iterator[RedisRestart]:
    """Restart the Redis master while Open Zaak creates zaken that a subscriber is notified of."""
    redis = operated(podiumd_env, OWNER_KIND, OPERATOR)
    master = master_pod(podiumd_env)
    if redis is None or master is None:
        pytest.skip(f"no Redis master of a {OWNER_KIND} with {OPERATOR} on {podiumd_env.profile.name}")
    need_bootstrap("infra-mock-server")
    users = redis_deployments(podiumd_env)
    served = [component for component in redis_components(podiumd_env, users) if component in urls]
    callback = Callback.new(podiumd_env, run_tag)
    with own_registry(request, run_tag) as registry:
        filters = {"bronorganisatie": names.TEST_CATALOGUS_RSIN}
        make_abonnement(opennotificaties, registry, callback.url, "zaken", filters)
        before = cluster_state(podiumd_env)
        start = time.time()
        calls = {"oz_zaak_create": zaak_maker(podiumd_env, run_tag, registry, str(test_zaaktype["url"]))}
        with watched_load(podiumd_env, urls, served, calls, workers=2, pause=1) as (load, watch):
            load.run_for(CALM)
            restarted = time.time()
            restart_master(podiumd_env, master, REDIS_RECOVERY)
            back = time.time()
            load.run_for(REDIS_AFTERMATH)
        zaken = load.created()
        recovered = recovery_seconds(load.attempts, restarted)
        yield RedisRestart(
            failed=failures(load.attempts, restarted),
            restarted=disruptions(before, cluster_state(podiumd_env), {redis.statefulset}),
            report=load_report(load, watch, start),
            measured={"redis_deployments": users, "redis_back_seconds": round(back - restarted)},
            lost=callback.missing(zaken, DELIVERY_TIMEOUT),
            created=len(zaken),
            silent=[component for component in served if not is_root_answering(http, urls[component], ROOT_TIMEOUT)],
            recovered=recovered,
        )


REDIS_REQUIRES = pytest.mark.requires("openzaak", "opennotificaties")
REDIS_SOURCE = pytest.mark.source(
    "podiumd-tests",
    "Redis is the cache and Celery broker of the Maykin apps; no source test restarts it under load.",
)


@REDIS_REQUIRES
@REDIS_SOURCE
@pytest.mark.scenario("""
    Given a subscriber on kanaal zaken in Open Notificaties
    And zaken are created in Open Zaak without pause
    When Redis is restarted
    Then the subscriber gets the notification of every zaak Open Zaak created
""")
def test_no_notificatie_is_lost_when_redis_restarts(
    redis_restart: RedisRestart, record_property: Callable[[str, object], None]
) -> None:
    """Every zaak Open Zaak creates around a Redis restart reaches the subscriber."""
    record_property("measured", redis_restart.measured)
    record_property("report", redis_restart.report)
    lost = redis_restart.lost
    assert lost == [], f"{len(lost)} of {redis_restart.created} notificaties lost"


@REDIS_REQUIRES
@REDIS_SOURCE
@pytest.mark.scenario("""
    Given zaken are created in Open Zaak without pause
    When Redis is restarted
    Then Open Zaak creates zaken again once Redis is back
    And every component that uses Redis answers again
""")
def test_redis_users_recover_after_a_restart(redis_restart: RedisRestart) -> None:
    """Open Zaak creates zaken again and every component that uses Redis answers after the restart."""
    assert redis_restart.silent == [], f"not answering after the Redis restart: {redis_restart.silent}"
    assert redis_restart.recovered is not None, f"Open Zaak creates no zaken again: {redis_restart.failed}"


@REDIS_REQUIRES
@REDIS_SOURCE
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="[open-inwoner-7] Open Inwoner 2.5.0's celery-monitor exits on a Redis restart and its worker stalls"
    " until the liveness probe kills it; neither reconnects; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given the components of the environment run
    When Redis is restarted
    Then no other container restarts
""")
def test_no_other_container_restarts_when_redis_restarts(redis_restart: RedisRestart) -> None:
    """No container besides Redis's restarts around a Redis restart."""
    assert redis_restart.restarted == []


@pytest.fixture(scope="module", name="solr_outage")
def fixture_solr_outage(
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    urls: dict[str, str],
    run_tag: str,
    openzaak: ApiClient,
    need_bootstrap: Callable[..., None],
) -> Iterator[SolrOutage]:
    """Stop ZAC's Solr while the test admin opens a zaak, searches and a new zaak arrives."""
    solr = operated(podiumd_env, SOLR_OWNER_KIND, SOLR_OPERATOR)
    if solr is None:
        pytest.skip(f"no Solr of a {SOLR_OWNER_KIND} with {SOLR_OPERATOR} on {podiumd_env.profile.name}")
    need_bootstrap(ADMIN.name, "openzaak-zaaktype-bpmn", "zac-bpmn-process")
    zac, zac_url = zac_as_admin(podiumd_env), urls["zac"]
    zaaktype = str(published_zaaktype(openzaak, names.BPMN_ZAAKTYPE, "openzaak-zaaktype-bpmn")["url"])
    with own_registry(request, run_tag) as registry:
        known = make_zaak(openzaak, registry, zaaktype)
        wait_until(lambda: is_zaak_listed(zac, zac_url, known), timeout=INDEX_TIMEOUT, description="the zaak indexed")
        before = cluster_state(podiumd_env)
        start = time.time()
        calls = {"zac_zaak_page": lambda: read_zaak(zac, zac_url, str(known["uuid"]))}
        with watched_load(podiumd_env, urls, ["zac"], calls, workers=1, pause=2) as (load, watch):
            with operated_down(podiumd_env.kube, solr, SOLR_RESTORE_TIMEOUT):
                asked = time.monotonic()
                search = search_failure(zac, zac_url)
                answered = round(time.monotonic() - asked, 1)
                arrived = make_zaak(openzaak, registry, zaaktype)
                load.run_for(SOLR_OUTAGE)
            down = round(time.time() - start)
        wait_until(lambda: is_zaak_listed(zac, zac_url, known), timeout=INDEX_TIMEOUT, description="ZAC's search")
        with suppress(WaitTimeoutError):
            wait_until(lambda: is_zaak_listed(zac, zac_url, arrived), timeout=INDEX_TIMEOUT, description="new zaak")
        yield SolrOutage(
            failed=failures(load.attempts, start),
            restarted=disruptions(before, cluster_state(podiumd_env), {solr.statefulset, solr.operator}),
            report=load_report(load, watch, start),
            measured={"search_seconds": answered, "search_answer": search, "solr_down_seconds": down},
            search=search,
            found=is_zaak_listed(zac, zac_url, arrived),
        )


SOLR_REQUIRES = pytest.mark.requires("zac", "openzaak", "opennotificaties", "keycloak", "pabc")
SOLR_SOURCE = pytest.mark.source(
    "podiumd-tests",
    "ZAC keeps its search index in its own Solr; no source test stops Solr while ZAC is in use.",
)


@SOLR_REQUIRES
@SOLR_SOURCE
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="[zac-38] ZAC 5.9.1's readiness check includes Solr: after 20 failed probes the pod leaves its"
    " Service and every page answers 502; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a behandelaar has a zaak open in ZAC
    When ZAC's Solr is stopped for four minutes
    Then the zaak keeps opening in ZAC
""")
def test_zaak_pages_keep_opening_while_solr_is_stopped(
    solr_outage: SolrOutage, record_property: Callable[[str, object], None]
) -> None:
    """The zaak page answers throughout a Solr outage."""
    record_property("measured", solr_outage.measured)
    record_property("report", solr_outage.report)
    assert solr_outage.failed == [], "the zaak page failed while Solr was down"


@SOLR_REQUIRES
@SOLR_SOURCE
@pytest.mark.scenario("""
    Given a behandelaar is logged in to ZAC
    When ZAC's Solr is stopped
    Then ZAC's search answers with an error instead of hanging
""")
def test_search_fails_fast_while_solr_is_stopped(solr_outage: SolrOutage) -> None:
    """ZAC's search answers an error, not a timeout, while Solr is down."""
    assert solr_outage.search is not None, "ZAC's search answered while Solr was down"
    assert "Timeout" not in solr_outage.search, f"ZAC's search hangs while Solr is down: {solr_outage.search}"


@SOLR_REQUIRES
@SOLR_SOURCE
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="[zac-39] ZAC 5.9.1 logs and drops the indexing of a notification it gets while Solr is down;"
    " no retry; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given ZAC's Solr is stopped
    When a zaak is created in Open Zaak
    And Solr is started again
    Then ZAC's search finds the zaak
""")
def test_a_zaak_made_while_solr_is_stopped_is_found(solr_outage: SolrOutage) -> None:
    """A zaak created while Solr is down is found by ZAC's search once Solr is back."""
    assert solr_outage.found, f"ZAC's search does not find the zaak {INDEX_TIMEOUT} s after Solr is back"


@SOLR_REQUIRES
@SOLR_SOURCE
@pytest.mark.scenario("""
    Given the components of the environment run
    When ZAC's Solr is stopped and started again
    Then no other container restarts
""")
def test_no_other_container_restarts_when_solr_stops(solr_outage: SolrOutage) -> None:
    """No container besides Solr's and its operator's restarts around a Solr outage."""
    assert solr_outage.restarted == []
