"""Continuity when KISS's Elasticsearch restarts: KISS keeps answering and its search comes back.

A module-scoped fixture restarts the Elasticsearch pod once while the KCC medewerker searches; each test checks one
consequence.
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
    pytest.mark.requires("kiss", "keycloak", "cluster"),
    pytest.mark.source(
        "podiumd-tests",
        "KISS searches its own Elasticsearch; no source test restarts it while KISS is in use.",
    ),
]

# ECK's label naming the Elasticsearch cluster of a pod; KISS's cluster is called kiss.
CLUSTER_LABEL = "elasticsearch.k8s.elastic.co/cluster-name"
KISS_CLUSTER = "kiss"
# An Elasticsearch pod restarts, recovers its shards and turns ready within this time.
ELASTICSEARCH_RECOVERY = 600
# Seconds of load after Elasticsearch is ready again.
AFTERMATH = 60


@dataclass(frozen=True)
class ElasticsearchRestart:
    """What restarting KISS's Elasticsearch did to KISS's pages and search."""

    page_failures: list[str]
    search_recovered: float | None
    search_failures: list[str]
    restarted: list[Disruption]
    report: str


@pytest.fixture(scope="module", name="kiss_elasticsearch_restart")
def fixture_kiss_elasticsearch_restart(  # fixtures
    browser: Browser,
    browser_context_args: dict[str, object],
    podiumd_env: Environment,
    urls: dict[str, str],
    http: requests.Session,
    need_bootstrap: Callable[..., None],
) -> ElasticsearchRestart:
    """Restart KISS's Elasticsearch pod while the KCC medewerker searches and KISS's start page is opened."""
    pods = [pod for pod in podiumd_env.items("pods") if metadata_labels(pod).get(CLUSTER_LABEL) == KISS_CLUSTER]
    if len(pods) != 1:
        pytest.skip(f"no single Elasticsearch pod of cluster {KISS_CLUSTER} on {podiumd_env.profile.name}")
    need_bootstrap(KCC.name)
    context = browser.new_context(**browser_context_args)  # pyright: ignore[reportArgumentType]
    kiss_url = urls["kiss"]
    kiss = kcc_login(guard_navigation(context.new_page()), podiumd_env, "kiss")
    context.close()
    calls = {
        "kiss_page": lambda: expect_status(http.get(kiss_url), 200),
        "kiss_search": lambda: kiss_search_hits(kiss, kiss_url, "podiumd"),
    }
    before = cluster_state(podiumd_env)
    start = time.time()
    with watched_load(podiumd_env, urls, ["kiss"], calls, workers=1, pause=1) as (load, watch):
        load.run_for(CALM)
        restarted = time.time()
        replace_pod(podiumd_env, pods[0], ELASTICSEARCH_RECOVERY)
        load.run_for(AFTERMATH)
    searches = [attempt for attempt in load.attempts if attempt.name == "kiss_search"]
    pages = [attempt for attempt in load.attempts if attempt.name == "kiss_page"]
    return ElasticsearchRestart(
        page_failures=failures(pages, restarted),
        search_recovered=recovery_seconds(searches, restarted),
        search_failures=failures(searches, restarted),
        restarted=disruptions(before, cluster_state(podiumd_env), {str(pod_workload(pods[0]))}),
        report=load_report(load, watch, start),
    )


@pytest.mark.scenario("""
    Given the KCC medewerker uses KISS
    When KISS's Elasticsearch restarts
    Then KISS's start page keeps opening
""")
def test_kiss_answers_while_elasticsearch_restarts(
    kiss_elasticsearch_restart: ElasticsearchRestart, record_property: Callable[[str, object], None]
) -> None:
    """KISS's start page answers throughout an Elasticsearch restart."""
    record_property("report", kiss_elasticsearch_restart.report)
    assert kiss_elasticsearch_restart.page_failures == []


@pytest.mark.scenario("""
    Given the KCC medewerker searches in KISS
    When KISS's Elasticsearch restarts
    Then KISS's search answers again once Elasticsearch is back
""")
def test_kiss_search_recovers_after_an_elasticsearch_restart(kiss_elasticsearch_restart: ElasticsearchRestart) -> None:
    """KISS's search answers again after Elasticsearch restarted."""
    restart = kiss_elasticsearch_restart
    assert restart.search_recovered is not None, f"KISS's search does not answer again: {restart.search_failures}"


@pytest.mark.scenario("""
    Given the components of the environment run
    When KISS's Elasticsearch restarts
    Then no other container restarts
""")
def test_no_other_container_restarts_when_elasticsearch_restarts(
    kiss_elasticsearch_restart: ElasticsearchRestart,
) -> None:
    """No container besides Elasticsearch's restarts around its restart."""
    assert kiss_elasticsearch_restart.restarted == []
