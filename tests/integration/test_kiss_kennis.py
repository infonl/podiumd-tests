"""Chain: an Objecten VAC or kennisartikel becomes findable in KISS after its elastic-sync job.

Ported from TA regression 190, which only counted documents in KISS's indices; on a fresh
environment they are empty. The test runs the sync CronJob once itself (schedule: workday hours)
and, at cleanup, again after deleting the object, so the index drops it.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kennisartikel_data
from podiumd_tests.kcc import kiss_sync_cronjob
from podiumd_tests.kcc import vac_data
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.workloads import run_cronjob

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.requires("kiss", "objecten", "keycloak", "cluster"),
    # Each sync rewrites its whole index.
    pytest.mark.xdist_group("kiss-sync"),
]


@pytest.mark.parametrize(
    ("objecttype", "source", "data"),
    [("VAC", "vac", vac_data), ("Kennisartikel", "kennisbank", kennisartikel_data)],
    ids=["vac", "kennisartikel"],
)
def test_object_is_found_in_kiss_search(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
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
    response = kiss.post(
        podiumd_env.profile.urls["kiss"] + "/api/search", json={"query": titel, "page": 1, "filters": []}
    )
    hits = entries(section(expect_status(response, HTTPStatus.OK).json(), "hits").get("hits"))
    assert any(titel in str(hit.get("_source")) for hit in hits), [hit.get("_index") for hit in hits]
