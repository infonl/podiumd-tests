"""Continuity when a shared store stops: Postgres, Redis (cache and Celery broker of the Maykin apps) and ZAC's Solr.

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

from podiumd_tests import redis as redis_ha
from podiumd_tests import zac as zac_app
from podiumd_tests import zac_search
from podiumd_tests.bootstrap import names
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.chaos_load import CALM
from podiumd_tests.chaos_load import DELIVERY_TIMEOUT
from podiumd_tests.chaos_load import failures
from podiumd_tests.chaos_load import load_report
from podiumd_tests.chaos_load import recovery_seconds
from podiumd_tests.chaos_load import watched_load
from podiumd_tests.components import COMPONENTS
from podiumd_tests.components import DJANGO_APPS
from podiumd_tests.defects import DefectSymptomError
from podiumd_tests.defects import symptom
from podiumd_tests.mock_server import Callback
from podiumd_tests.responses import is_root_answering
from podiumd_tests.responses import page_problem
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
from podiumd_tests.workloads import database_pod
from podiumd_tests.workloads import disruptions
from podiumd_tests.workloads import operated
from podiumd_tests.workloads import operated_down
from podiumd_tests.workloads import pod_workload
from podiumd_tests.workloads import replace_pod

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator
    from collections.abc import Iterator

    import requests

    from podiumd_tests.chaos_load import Calls
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

# A deleted Redis or Postgres pod is replaced (and the Redis operator labels it master).
STORE_RECOVERY = 300
# Seconds of load after the store is back: longer than the slowest liveness probe of the workers to kill a process
# stuck since the restart (Open Zaak and Open Klant: 6 x 60 s).
AFTERMATH = 420
# Seconds ZAC's Solr stays stopped: longer than ZAC's readiness probe tolerates a failing check (20 x 10 s).
SOLR_OUTAGE = 240
# Admin login pages per Django app after a Redis restart: enough to reach each of its uWSGI workers, which hold
# their own Redis connections (IN-3210: the first load answered 504, the next one 200).
ADMIN_LOGINS = 20
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
class StoreRestart(Outage):
    """What a store's restart under load did to Open Zaak, its subscriber and the store's users."""

    lost: list[str]
    created: int
    silent: list[str]
    recovered: dict[str, float | None]


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


def restart_under_load(
    request: pytest.FixtureRequest,
    env: Environment,
    urls: dict[str, str],
    http: requests.Session,
    opennotificaties: ApiClient,
    zaaktype: str,
    served: list[str],
    restart: Callable[[], None],
    stopped: set[str],
    extra: Calls,
) -> StoreRestart:
    """Run `restart` while Open Zaak creates zaken that a subscriber is notified of, and keep the load on after it.

    The extra calls run in the same load; `recovered` holds the recovery of each call.
    """
    run_tag = str(request.getfixturevalue("run_tag"))
    callback = Callback.new(env, run_tag)
    with own_registry(request, run_tag) as registry:
        filters = {"bronorganisatie": names.TEST_CATALOGUS_RSIN}
        make_abonnement(opennotificaties, registry, callback.url, "zaken", filters)
        before = cluster_state(env)
        start = time.time()
        calls = {"oz_zaak_create": zaak_maker(env, run_tag, registry, zaaktype), **extra}
        with watched_load(env, urls, served, calls, workers=2, pause=1) as (load, watch):
            load.run_for(CALM)
            restarted = time.time()
            restart()
            back = time.time()
            load.run_for(AFTERMATH)
        zaken = load.created(name="oz_zaak_create")
        return StoreRestart(
            failed=failures(load.attempts, restarted),
            restarted=disruptions(before, cluster_state(env), stopped),
            report=load_report(load, watch, start),
            measured={"back_seconds": round(back - restarted)},
            lost=callback.missing(zaken, DELIVERY_TIMEOUT),
            created=len(zaken),
            silent=[component for component in served if not is_root_answering(http, urls[component], ROOT_TIMEOUT)],
            recovered={
                name: recovery_seconds([attempt for attempt in load.attempts if attempt.name == name], restarted)
                for name in calls
            },
        )


@pytest.fixture(scope="module", name="redis_restart")
def fixture_redis_restart(  # fixtures
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    urls: dict[str, str],
    http: requests.Session,
    opennotificaties: ApiClient,
    test_zaaktype: JsonObject,
    need_bootstrap: Callable[..., None],
) -> StoreRestart:
    """Restart the Redis master while Open Zaak creates zaken that a subscriber is notified of."""
    replication = operated(podiumd_env, redis_ha.OWNER_KIND, redis_ha.OPERATOR)
    master = redis_ha.master_pod(podiumd_env)
    if replication is None or master is None:
        kind, operator = redis_ha.OWNER_KIND, redis_ha.OPERATOR
        pytest.skip(f"no Redis master of a {kind} with {operator} on {podiumd_env.profile.name}")
    need_bootstrap("infra-mock-server")
    users = redis_ha.redis_deployments(podiumd_env)
    served = [component for component in redis_ha.redis_components(podiumd_env, users) if component in urls]
    outcome = restart_under_load(
        request,
        podiumd_env,
        urls,
        http,
        opennotificaties,
        str(test_zaaktype["url"]),
        served,
        lambda: redis_ha.restart_master(podiumd_env, master, STORE_RECOVERY),
        {replication.statefulset},
        {},
    )
    outcome.measured["redis_deployments"] = users
    return outcome


@pytest.fixture(scope="module", name="postgres_restart")
def fixture_postgres_restart(  # fixtures
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    urls: dict[str, str],
    http: requests.Session,
    opennotificaties: ApiClient,
    test_zaaktype: JsonObject,
    need_bootstrap: Callable[..., None],
) -> StoreRestart:
    """Restart the in-cluster Postgres while Open Zaak creates zaken that a subscriber is notified of."""
    database = database_pod(podiumd_env)
    if database is None:
        pytest.skip(f"Open Zaak's database runs outside the cluster on {podiumd_env.profile.name}")
    need_bootstrap("infra-mock-server")
    served = sorted(component for component in urls if component in COMPONENTS)
    extra: Calls = {}
    if "zac" in urls:
        need_bootstrap(ADMIN.name)
        zac, zac_url = zac_as_admin(podiumd_env), urls["zac"]
        # Read from ZAC's own database through its connection pool.
        extra = {"zac_zaakafhandelparameters": lambda: zac_app.zaakafhandelparameters(zac, zac_url)}
    return restart_under_load(
        request,
        podiumd_env,
        urls,
        http,
        opennotificaties,
        str(test_zaaktype["url"]),
        served,
        lambda: replace_pod(podiumd_env, database, STORE_RECOVERY),
        {str(pod_workload(database))},
        extra,
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
    redis_restart: StoreRestart, record_property: Callable[[str, object], None]
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
def test_redis_users_recover_after_a_restart(redis_restart: StoreRestart) -> None:
    """Open Zaak creates zaken again and every component that uses Redis answers after the restart."""
    assert redis_restart.silent == [], f"not answering after the Redis restart: {redis_restart.silent}"
    assert redis_restart.recovered["oz_zaak_create"] is not None, (
        f"Open Zaak creates no zaken again: {redis_restart.failed}"
    )


@REDIS_REQUIRES
@REDIS_SOURCE
@pytest.mark.xfail(
    strict=True,
    raises=DefectSymptomError,
    reason="[maykin-common-1] maykin-common 0.22.0 and 0.23.0 stop touching the event-loop liveness file once Celery"
    " reconnects to its broker, so the liveness probe kills the working workers of Open Zaak, Open Klant, Open VTB and"
    " Open Inwoner; [open-inwoner-7] Open Inwoner 2.5.0's celery-monitor exits on a Redis restart; not yet reported"
    " upstream",
)
@pytest.mark.scenario("""
    Given the components of the environment run
    When Redis is restarted
    Then no other container restarts
""")
def test_no_other_container_restarts_when_redis_restarts(redis_restart: StoreRestart) -> None:
    """No container besides Redis's restarts around a Redis restart."""
    with symptom():
        assert redis_restart.restarted == []


@REDIS_REQUIRES
@REDIS_SOURCE
@pytest.mark.source(
    "Jira IN-3210", "Objecten's /admin answers 504 or 500 after a Redis failover until the pod restarts."
)
@pytest.mark.scenario("""
    Given Redis was restarted while the apps ran
    When the admin login page of each Django app that uses Redis is opened 20 times
    Then every page answers without a server error or a timeout
""")
def test_admin_login_answers_once_redis_is_back(
    redis_restart: StoreRestart, podiumd_env: Environment, http: requests.Session, urls: dict[str, str]
) -> None:
    """No uWSGI worker of a Redis-using Django app answers its admin login page with a 5xx or a timeout."""
    users = redis_ha.redis_components(podiumd_env, redis_ha.redis_deployments(podiumd_env))
    apps = [app for app in users if app in DJANGO_APPS and app in urls]
    found = {
        app: [page_problem(http, f"{urls[app]}/admin/login/", ROOT_TIMEOUT) for _ in range(ADMIN_LOGINS)]
        for app in apps
    }
    failing = {app: [problem for problem in problems if problem] for app, problems in found.items()}
    assert {app: problems for app, problems in failing.items() if problems} == {}, redis_restart.report


@REDIS_REQUIRES
@REDIS_SOURCE
@pytest.mark.source("podiumd-tests", "podiumd-chart-28: an app connection that stays on a replica fails every write.")
@pytest.mark.scenario("""
    Given Redis was restarted while the apps ran
    When the clients of each Redis replica are listed
    Then no app is connected to a replica
""")
@pytest.mark.usefixtures("redis_restart")
def test_no_app_stays_on_a_redis_replica_after_a_restart(podiumd_env: Environment) -> None:
    """After a Redis restart, the replicas have no client but their replication link, Sentinel and their own pod."""
    connected = redis_ha.replica_app_connections(podiumd_env)
    assert connected == {}, f"app connections on Redis replicas: {connected}"


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
    solr = operated(podiumd_env, zac_app.SOLR_OWNER_KIND, zac_app.SOLR_OPERATOR)
    if solr is None:
        pytest.skip(
            f"no Solr of a {zac_app.SOLR_OWNER_KIND} with {zac_app.SOLR_OPERATOR} on {podiumd_env.profile.name}"
        )
    need_bootstrap(ADMIN.name, "openzaak-zaaktype-bpmn", "zac-bpmn-process")
    zac, zac_url = zac_as_admin(podiumd_env), urls["zac"]
    zaaktype = str(published_zaaktype(openzaak, names.BPMN_ZAAKTYPE, "openzaak-zaaktype-bpmn")["url"])
    with own_registry(request, run_tag) as registry:
        known = make_zaak(openzaak, registry, zaaktype)
        wait_until(
            lambda: zac_search.is_zaak_listed(zac, zac_url, known),
            timeout=zac_app.INDEX_TIMEOUT,
            description="the zaak indexed",
        )
        before = cluster_state(podiumd_env)
        start = time.time()
        calls = {"zac_zaak_page": lambda: zac_app.read_zaak(zac, zac_url, str(known["uuid"]))}
        with watched_load(podiumd_env, urls, ["zac"], calls, workers=1, pause=2) as (load, watch):
            with operated_down(podiumd_env.kube, solr, SOLR_RESTORE_TIMEOUT):
                asked = time.monotonic()
                search = zac_search.search_failure(zac, zac_url)
                answered = round(time.monotonic() - asked, 1)
                arrived = make_zaak(openzaak, registry, zaaktype)
                load.run_for(SOLR_OUTAGE)
            down = round(time.time() - start)
        wait_until(
            lambda: zac_search.is_zaak_listed(zac, zac_url, known),
            timeout=zac_app.INDEX_TIMEOUT,
            description="ZAC's search",
        )
        with suppress(WaitTimeoutError):
            wait_until(
                lambda: zac_search.is_zaak_listed(zac, zac_url, arrived),
                timeout=zac_app.INDEX_TIMEOUT,
                description="new zaak",
            )
        yield SolrOutage(
            failed=failures(load.attempts, start),
            restarted=disruptions(before, cluster_state(podiumd_env), {solr.statefulset, solr.operator}),
            report=load_report(load, watch, start),
            measured={"search_seconds": answered, "search_answer": search, "solr_down_seconds": down},
            search=search,
            found=zac_search.is_zaak_listed(zac, zac_url, arrived),
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
    raises=DefectSymptomError,
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
    with symptom():
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
    raises=DefectSymptomError,
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
    with symptom():
        assert solr_outage.found, f"ZAC's search does not find the zaak {zac_app.INDEX_TIMEOUT} s after Solr is back"


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


POSTGRES_REQUIRES = pytest.mark.requires("openzaak", "opennotificaties")
POSTGRES_SOURCE = pytest.mark.source(
    "podiumd-tests",
    "The apps share one Postgres server; no source test restarts it under load.",
)


@POSTGRES_REQUIRES
@POSTGRES_SOURCE
@pytest.mark.xfail(
    strict=True,
    raises=DefectSymptomError,
    reason="[open-zaak-17] Open Zaak 1.29.3 (notifications-api-common 0.10.1) does not retry a send_notification"
    " that fails on its dead database connection after a Postgres restart; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a subscriber on kanaal zaken in Open Notificaties
    And zaken are created in Open Zaak without pause
    When the database server is restarted
    Then the subscriber gets the notification of every zaak Open Zaak created
""")
def test_no_notificatie_is_lost_when_postgres_restarts(
    postgres_restart: StoreRestart, record_property: Callable[[str, object], None]
) -> None:
    """Every zaak Open Zaak creates around a Postgres restart reaches the subscriber."""
    record_property("measured", postgres_restart.measured)
    record_property("report", postgres_restart.report)
    lost = postgres_restart.lost
    with symptom():
        assert lost == [], f"{len(lost)} of {postgres_restart.created} notificaties lost"


@POSTGRES_REQUIRES
@POSTGRES_SOURCE
@pytest.mark.scenario("""
    Given zaken are created in Open Zaak without pause
    And the test admin reads ZAC's zaakafhandelparameters without pause
    When the database server is restarted
    Then Open Zaak creates zaken and ZAC reads its database again once the database is back
    And every component answers again
""")
def test_components_recover_when_postgres_restarts(postgres_restart: StoreRestart) -> None:
    """Open Zaak creates zaken, ZAC reads its database and every component answers after the restart."""
    assert postgres_restart.silent == [], f"not answering after the Postgres restart: {postgres_restart.silent}"
    unrecovered = [name for name, seconds in postgres_restart.recovered.items() if seconds is None]
    assert unrecovered == [], f"failing again after the Postgres restart: {unrecovered}: {postgres_restart.failed}"


@POSTGRES_REQUIRES
@POSTGRES_SOURCE
@pytest.mark.scenario("""
    Given the components of the environment run
    When the database server is restarted
    Then no other container restarts
""")
def test_no_other_container_restarts_when_postgres_restarts(postgres_restart: StoreRestart) -> None:
    """No container besides Postgres's restarts around a Postgres restart."""
    assert postgres_restart.restarted == []
