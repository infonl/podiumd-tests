"""Continuity when an app's Elasticsearch restarts: the app keeps answering and its search comes back.

KISS and Open Inwoner each search their own Elasticsearch. A module-scoped fixture restarts it once per app while
the app is used; each test checks one consequence.
"""

from __future__ import annotations

import time

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.browser import guard_navigation
from podiumd_tests.chaos_load import CALM
from podiumd_tests.chaos_load import failures
from podiumd_tests.chaos_load import load_report
from podiumd_tests.chaos_load import recovery_seconds
from podiumd_tests.chaos_load import watched_load
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kiss_search_hits
from podiumd_tests.kube import metadata_labels
from podiumd_tests.openinwoner import search_page
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import expect_status
from podiumd_tests.workloads import cluster_state
from podiumd_tests.workloads import disruptions
from podiumd_tests.workloads import pod_workload
from podiumd_tests.workloads import replace_pod

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Browser

    from podiumd_tests.environment import Environment
    from podiumd_tests.workloads import Disruption

pytestmark = [
    pytest.mark.integration,
    pytest.mark.destructive,
    pytest.mark.slow,
    pytest.mark.requires("cluster"),
    pytest.mark.source(
        "podiumd-tests",
        "KISS and Open Inwoner search their own Elasticsearch; no source test restarts it while the app is in use.",
    ),
]

# ECK's label naming the Elasticsearch cluster of a pod; each app's cluster name starts with the app's name.
CLUSTER_LABEL = "elasticsearch.k8s.elastic.co/cluster-name"
# An Elasticsearch pod restarts, recovers its shards and turns ready within this time.
ELASTICSEARCH_RECOVERY = 600
# Seconds of load after Elasticsearch is ready again.
AFTERMATH = 60


@dataclass(frozen=True)
class ElasticsearchRestart:
    """What restarting an app's Elasticsearch did to the app's start page and search."""

    app: str
    page_failures: list[str]
    search_recovered: float | None
    search_failures: list[str]
    restarted: list[Disruption]
    report: str


def searcher(
    request: pytest.FixtureRequest, env: Environment, http: requests.Session, app: str
) -> Callable[[], object]:
    """Return a search in the app: KISS's as the KCC medewerker, Open Inwoner's as an anonymous visitor."""
    url = env.profile.urls[app]
    if app == "openinwoner":
        return lambda: search_page(http, url, query="informatie")
    request.getfixturevalue("need_bootstrap")(KCC.name)
    browser: Browser = request.getfixturevalue("browser")
    context = browser.new_context(**request.getfixturevalue("browser_context_args"))
    kiss = kcc_login(guard_navigation(context.new_page()), env, app)
    context.close()
    return lambda: kiss_search_hits(kiss, url, "podiumd")


@pytest.fixture(
    scope="module",
    name="search_index_restart",
    params=[
        requiring("kiss", "kiss", marks=[pytest.mark.requires("keycloak")]),
        requiring("openinwoner", "openinwoner"),
    ],
)
def fixture_search_index_restart(
    request: pytest.FixtureRequest, podiumd_env: Environment, urls: dict[str, str], http: requests.Session
) -> ElasticsearchRestart:
    """Restart the app's Elasticsearch pod while its start page is opened and its search is used."""
    app = str(request.param)
    pods = [
        pod for pod in podiumd_env.items("pods") if str(metadata_labels(pod).get(CLUSTER_LABEL, "")).startswith(app)
    ]
    if len(pods) != 1:
        pytest.skip(f"no single Elasticsearch pod of {app} on {podiumd_env.profile.name}")
    app_url = urls[app]
    calls = {"page": lambda: expect_status(http.get(app_url), 200), "search": searcher(request, podiumd_env, http, app)}
    before = cluster_state(podiumd_env)
    start = time.time()
    with watched_load(podiumd_env, urls, [app], calls, workers=1, pause=1) as (load, watch):
        load.run_for(CALM)
        restarted = time.time()
        replace_pod(podiumd_env, pods[0], ELASTICSEARCH_RECOVERY)
        load.run_for(AFTERMATH)
    searches = [attempt for attempt in load.attempts if attempt.name == "search"]
    pages = [attempt for attempt in load.attempts if attempt.name == "page"]
    return ElasticsearchRestart(
        app=app,
        page_failures=failures(pages, restarted),
        search_recovered=recovery_seconds(searches, restarted),
        search_failures=failures(searches, restarted),
        restarted=disruptions(before, cluster_state(podiumd_env), {str(pod_workload(pods[0]))}),
        report=load_report(load, watch, start),
    )


@pytest.mark.scenario("""
    Given a KCC medewerker uses KISS, or a visitor uses Open Inwoner
    When the app's Elasticsearch restarts
    Then the app's start page keeps opening
""")
def test_app_answers_while_its_elasticsearch_restarts(
    search_index_restart: ElasticsearchRestart, record_property: Callable[[str, object], None]
) -> None:
    """The app's start page answers throughout an Elasticsearch restart."""
    record_property("report", search_index_restart.report)
    assert search_index_restart.page_failures == []


@pytest.mark.scenario("""
    Given a KCC medewerker searches in KISS, or a visitor searches in Open Inwoner
    When the app's Elasticsearch restarts
    Then the app's search answers again once Elasticsearch is back
""")
def test_search_recovers_after_an_elasticsearch_restart(search_index_restart: ElasticsearchRestart) -> None:
    """The app's search answers again after its Elasticsearch restarted."""
    restart = search_index_restart
    assert restart.search_recovered is not None, (
        f"{restart.app}'s search does not answer again: {restart.search_failures}"
    )


@pytest.mark.scenario("""
    Given the components of the environment run
    When an app's Elasticsearch restarts
    Then no other container restarts
""")
def test_no_other_container_restarts_when_elasticsearch_restarts(
    search_index_restart: ElasticsearchRestart,
) -> None:
    """No container besides Elasticsearch's restarts around its restart."""
    assert search_index_restart.restarted == []
