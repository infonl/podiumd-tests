"""Open Archiefbeheer: the destruction of a large vernietigingslijst of the test's own zaken, also when Open Zaak stops.

Destructive (tier chaos): it sets OAB's global ArchiveConfig, loads its worker and Open Zaak, and stops Open Zaak.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.oab import destroy
from podiumd_tests.oab import destroy_now
from podiumd_tests.oab import due_zaken
from podiumd_tests.oab import processed_status
from podiumd_tests.oab import queue
from podiumd_tests.oab import ready_to_delete
from podiumd_tests.oab import report_config
from podiumd_tests.perf.availability import watched
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.perf.availability_report import report
from podiumd_tests.workloads import component_down

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.cluster,
    pytest.mark.destructive,
    pytest.mark.slow,
    pytest.mark.requires("openarchiefbeheer", "openzaak", "cluster"),
]

# Seconds OAB may take: a base for the report, and per zaak.
DESTRUCTION_BASE = 120
DESTRUCTION_PER_ZAAK = 1
# Zaken of the list Open Zaak stops under: enough that their destruction outlasts Open Zaak's stop.
INTERRUPTED_ZAKEN = 200


@pytest.mark.source(
    "upstream maykinmedia/open-archiefbeheer backend/src/openarchiefbeheer/destruction/tests/performance/"
    "test_performance.py",
    "Destroys a list of 10,000 zaken in the background; issues #496 and #655: tokens expired, a timed-out delete"
    " left the list processing.",
)
@pytest.mark.scenario("""
    Given hundreds of zaken due for destruction
    And a vernietigingslijst of them that the reviewer and the archivist accepted
    When the destruction runs
    Then the list is deleted and the report names every zaak
    And Open Archiefbeheer and Open Zaak did not restart and stayed within their memory limits
    And Open Zaak answered throughout
""")
def test_large_list_is_destroyed_without_disruption(  # fixtures
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    urls: dict[str, str],
    oab: Callable[[str], requests.Session],
    api: str,
    openzaak: ApiClient,
    parts: ZaaktypeParts,
    registry: ResourceRegistry,
    oab_config: Callable[..., None],
    record_property: Callable[[str, object], None],
) -> None:
    """OAB destroys a large list completely while its worker and Open Zaak stay within perf.yaml's availability."""
    count = int(str(request.config.getoption("--oab-destruction-zaken")))
    oab_config("ArchiveConfig", **report_config(parts))
    zaken = due_zaken(podiumd_env, openzaak, parts, registry, count)
    lijst = ready_to_delete(oab, api, zaken, registry)
    timeout = DESTRUCTION_BASE + DESTRUCTION_PER_ZAAK * count
    with watched(podiumd_env, urls, ["openarchiefbeheer", "openzaak"]) as watch:
        text = destroy(podiumd_env, oab, api, lijst, openzaak=openzaak, parts=parts, registry=registry, timeout=timeout)
    record_property("destruction_seconds", round(watch.ended - watch.started))
    record_property("report", report(watch, ""))
    assert [str(zaak["identificatie"]) for zaak in zaken if str(zaak["identificatie"]) not in text] == []
    assert problems(watch) == []


@pytest.mark.source(
    "upstream maykinmedia/open-archiefbeheer backend/src/openarchiefbeheer/destruction/tasks.py",
    "A failed destruction can be queued again; items already deleted are skipped.",
)
@pytest.mark.scenario("""
    Given a vernietigingslijst of two hundred zaken that the reviewer and the archivist accepted
    When Open Zaak stops while the destruction runs
    Then Open Archiefbeheer marks the destruction as failed
    When the record manager starts the destruction again once Open Zaak is back
    Then the list is deleted and the report names every zaak
""")
def test_destruction_interrupted_by_open_zaak_completes_on_retry(  # fixtures
    podiumd_env: Environment,
    http: requests.Session,
    oab: Callable[[str], requests.Session],
    api: str,
    openzaak: ApiClient,
    parts: ZaaktypeParts,
    registry: ResourceRegistry,
    oab_config: Callable[..., None],
) -> None:
    """A destruction that failed because Open Zaak stopped deletes every zaak and reports it when retried."""
    oab_config("ArchiveConfig", **report_config(parts))
    zaken = due_zaken(podiumd_env, openzaak, parts, registry, INTERRUPTED_ZAKEN)
    lijst = ready_to_delete(oab, api, zaken, registry)
    timeout = DESTRUCTION_BASE + DESTRUCTION_PER_ZAAK * INTERRUPTED_ZAKEN
    queue(oab, api, lijst)
    destroy_now(podiumd_env, lijst)
    with component_down(podiumd_env, http, "openzaak"):
        interrupted = processed_status(oab, api, lijst, timeout)
    assert interrupted == "failed", f"the destruction ended {interrupted} before Open Zaak stopped"
    text = destroy(
        podiumd_env, oab, api, lijst, openzaak=openzaak, parts=parts, registry=registry, timeout=timeout, retry=True
    )
    assert [str(zaak["identificatie"]) for zaak in zaken if str(zaak["identificatie"]) not in text] == []
