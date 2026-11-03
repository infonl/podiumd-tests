"""Chain: KISS's website crawler fills Elasticsearch, and KISS's search finds the crawled site.

The test runs each crawler CronJob once itself (schedule: once a workday), so it needs the crawled
site reachable from the cluster.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import section
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kiss_search_hits
from podiumd_tests.kcc import kiss_website_crawlers
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import run_cronjob

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.requires("kiss", "keycloak", "cluster"),
    pytest.mark.source("podiumd-tests", "Checks that KISS's search finds pages of a website its crawler indexed."),
]

# A crawl of a whole municipal site takes minutes.
CRAWL_TIMEOUT = 900


def test_crawled_website_is_found_in_kiss_search(
    page: Page, podiumd_env: Environment, registry: ResourceRegistry, need_bootstrap: Callable[..., None]
) -> None:
    """After a crawl, KISS's search for the site's name finds a page of that site."""
    crawlers = kiss_website_crawlers(podiumd_env)
    if not crawlers:
        pytest.skip(f"no KISS website on {podiumd_env.profile.name}: kiss.settings.syncJobs.website is empty")
    need_bootstrap(KCC.name)
    for cronjob in crawlers:
        run_cronjob(podiumd_env.kube, cronjob, registry.tagged(cronjob), timeout=CRAWL_TIMEOUT)
    kiss = kcc_login(page, podiumd_env, "kiss")
    for url in crawlers.values():
        host = urlsplit(url).hostname or url
        name = host.removeprefix("www.").split(".")[0]

        def found(host: str = host, name: str = name) -> bool:
            hits = kiss_search_hits(kiss, podiumd_env.profile.urls["kiss"], name)
            return any(section(hit, "_source").get("url_host") == host for hit in hits)

        # Elasticsearch shows new documents only after its next index refresh.
        wait_until(found, timeout=60, description=f"KISS search for {name!r} finds a page of {host}")
