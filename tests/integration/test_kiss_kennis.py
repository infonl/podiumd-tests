"""Chain: an Objecten VAC or kennisartikel becomes findable in KISS after its elastic-sync job.

Ported from TA regression 190, which only counted documents in KISS's indices; on a fresh
environment they are empty. The test runs the sync CronJob once itself (schedule: workday hours)
and, at cleanup, again after deleting the object, so the index drops it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.kcc import hit_afdeling
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kennisartikel_data
from podiumd_tests.kcc import kiss_search_hits
from podiumd_tests.kcc import kiss_search_sources
from podiumd_tests.kcc import kiss_sync_cronjob
from podiumd_tests.kcc import medewerker_data
from podiumd_tests.kcc import vac_data
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import run_cronjob

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.requires("kiss", "objecten", "keycloak", "cluster"),
    # Each sync rewrites its whole index.
    pytest.mark.xdist_group("kiss-sync"),
    pytest.mark.source(
        "TA regression/190-kiss-contentbronnen-gevuld.spec.ts",
        "Checks that KISS's content indices actually contain documents, not only that the endpoint answers.",
    ),
]


@pytest.mark.parametrize(
    ("objecttype", "source", "data"),
    [
        ("VAC", "vac", vac_data),
        ("Kennisartikel", "kennisbank", kennisartikel_data),
        ("Medewerker", "smoelenboek", medewerker_data),
    ],
    ids=["vac", "kennisartikel", "smoelenboek"],
)
@pytest.mark.scenario("""
    Given a new VAC, kennisartikel or medewerker in Objecten
    When KISS synchronises its search index
    Then the KCC medewerker finds it by its title in KISS's search
""")
def test_object_is_found_in_kiss_search(
    page: Page,
    podiumd_env: Environment,
    objecten: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    objecttype: str,
    source: str,
    data: Callable[[str], dict[str, object]],
) -> None:
    """After the sync job, KISS's search finds the new object by its title (TA reg-190)."""
    need_bootstrap(KCC.name, "objecten-token")
    cronjob = kiss_sync_cronjob(podiumd_env, source)
    titel = registry.tagged(f"kiss-{source}")
    registry.add(f"{source} index", lambda: run_cronjob(podiumd_env.kube, cronjob, f"{titel}-opruimen"))
    make_object(objecten, registry, objecttype_url(podiumd_env, objecttype), data(titel))
    run_cronjob(podiumd_env.kube, cronjob, titel)
    kiss = kcc_login(page, podiumd_env, "kiss")

    def is_found() -> bool:
        hits = kiss_search_hits(kiss, podiumd_env.profile.urls["kiss"], titel)
        return any(titel in str(hit.get("_source")) for hit in hits)

    # Elasticsearch shows new documents only after its next index refresh, which lags under load.
    wait_until(is_found, timeout=60, description=f"KISS search finds {titel}")


def _synced(  # the environment, cleanup and the object
    env: Environment, objecten: ApiClient, registry: ResourceRegistry, objecttype: str, source: str, data: JsonObject
) -> None:
    """Create the object in Objecten and run KISS's sync of the source; cleanup runs the sync again after deleting it."""
    cronjob = kiss_sync_cronjob(env, source)
    registry.add(f"{source} index", lambda: run_cronjob(env.kube, cronjob, registry.tagged(f"{source}-opruimen")))
    make_object(objecten, registry, objecttype_url(env, objecttype), data)
    run_cronjob(env.kube, cronjob, registry.tagged(source))


def _found(
    kiss: requests.Session, kiss_url: str, titel: str, sources: list[JsonObject] | None = None
) -> list[JsonObject]:
    """The hits of the search for the title in the sources whose record carries the title."""
    # Elasticsearch shows new documents only after its next index refresh, which lags under load.
    return wait_until(
        lambda: [hit for hit in kiss_search_hits(kiss, kiss_url, titel, sources) if titel in str(hit.get("_source"))],
        timeout=60,
        description=f"KISS search finds {titel}",
    )


@pytest.mark.parametrize("source", ["vac", "kennisbank"])
@pytest.mark.scenario("""
    Given a VAC and a kennisartikel with the same title
    When the KCC medewerker searches the title in KISS with the source filter on VAC or on Kennisbank
    Then KISS gives only hits of that source
""")
def test_source_filter_gives_only_that_source(
    page: Page,
    podiumd_env: Environment,
    objecten: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    source: str,
) -> None:
    """POST /api/search with one source in filters returns hits of that source's index only."""
    need_bootstrap(KCC.name, "objecten-token")
    titel = registry.tagged("kiss-filter")
    _synced(podiumd_env, objecten, registry, "VAC", "vac", vac_data(titel))
    _synced(podiumd_env, objecten, registry, "Kennisartikel", "kennisbank", kennisartikel_data(titel))
    kiss = kcc_login(page, podiumd_env, "kiss")
    kiss_url = podiumd_env.profile.urls["kiss"]
    chosen = [s for s in kiss_search_sources(kiss, kiss_url) if s.get("name") == source]
    hits = _found(kiss, kiss_url, titel, chosen)
    assert {hit.get("_index") for hit in hits} == {chosen[0]["index"]}


@pytest.mark.parametrize(
    ("objecttype", "source", "data", "key"),
    [("Kennisartikel", "kennisbank", kennisartikel_data, "afdelingnaam"), ("VAC", "vac", vac_data, "afdelingNaam")],
    ids=["kennisartikel", "vac"],
)
@pytest.mark.scenario("""
    Given a kennisartikel or VAC of an afdeling in Objecten, the kennisartikel's key afdelingnaam, the VAC's afdelingNaam
    When the KCC medewerker finds it in KISS's search
    Then KISS takes that afdeling from the hit
""")
def test_kennisartikel_hit_names_its_afdeling(  # fixtures
    page: Page,
    podiumd_env: Environment,
    objecten: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    objecttype: str,
    source: str,
    data: Callable[[str], dict[str, object]],
    key: str,
) -> None:
    """The hit's record keeps afdelingen; KISS reads afdelingnaam case-insensitively (getByCaseInsensitiveKey)."""
    need_bootstrap(KCC.name, "objecten-token")
    titel = registry.tagged(f"kiss-afdeling-{source}")
    afdeling = registry.tagged(f"afdeling-{source}")
    _synced(podiumd_env, objecten, registry, objecttype, source, {**data(titel), "afdelingen": [{key: afdeling}]})
    kiss = kcc_login(page, podiumd_env, "kiss")
    hits = _found(kiss, podiumd_env.profile.urls["kiss"], titel)
    assert [hit_afdeling(hit) for hit in hits] == [afdeling]
