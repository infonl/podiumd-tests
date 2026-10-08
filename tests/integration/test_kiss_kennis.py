"""Chain: an Objecten VAC or kennisartikel becomes findable in KISS after its elastic-sync job.

Ported from TA regression 190, which only counted documents in KISS's indices; on a fresh
environment they are empty. The test runs the sync CronJob once itself (schedule: workday hours)
and, at cleanup, again after deleting the object, so the index drops it.
"""

from __future__ import annotations

import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kube import metadata_name
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openzaak import today
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


def vac(titel: str) -> dict[str, object]:
    """A VAC (vraag-antwoordcombinatie) with the title as its question."""
    return {"vraag": titel, "antwoord": "Antwoord van podiumd-tests.", "doelgroep": "eu-burger", "status": "actief"}


def kennisartikel(titel: str) -> dict[str, object]:
    """An SDG kennisartikel with the title in its Dutch translation."""
    example = "https://example.invalid/"
    return {
        "url": example + titel,
        "uuid": str(uuid.uuid4()),
        "upnUri": example + "upn",
        "publicatieDatum": today(),
        "productAanwezig": True,
        "productValtOnder": None,
        "verantwoordelijkeOrganisatie": {
            "url": example + "organisatie",
            "owmsIdentifier": example + "owms",
            "owmsEndDate": "2099-12-31T00:00:00Z",
        },
        "locaties": None,
        "doelgroep": "eu-burger",
        "vertalingen": [{"taal": "nl", "datumWijziging": today(), "titel": titel, "tekst": "Tekst van podiumd-tests."}],
        "beschikbareTalen": ["nl"],
    }


def sync_cronjob(env: Environment, source: str) -> str:
    """The name of KISS's elastic-sync CronJob for the source, e.g. contact-vac-sync."""
    names = [metadata_name(c) for c in env.items("cronjobs")]
    return next(n for n in names if n.endswith(f"-{source}-sync"))


@pytest.mark.parametrize(
    ("objecttype", "source", "data"),
    [("VAC", "vac", vac), ("Kennisartikel", "kennisbank", kennisartikel)],
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
    cronjob = sync_cronjob(podiumd_env, source)
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
