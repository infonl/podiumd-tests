"""ZAC's dashboard lists of a user with more zaken than one page shows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import search
from podiumd_tests.zac import zac_session
from podiumd_tests.zac_signaleringen import save_signalering_setting
from podiumd_tests.zac_signaleringen import signalering_page

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    # ZAC signals a zaak on a user's name from Open Notificaties' notifications.
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "opennotificaties"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md,"
        " zoeken-werklijsten-dashboard): dashboard counts above 25.",
    ),
]

ZAAK_OP_NAAM = "ZAAK_OP_NAAM"
# The rows of a dashboard card's page in ZAC's UI, and one zaak more.
ROWS = 25
ZAKEN = ROWS + 1


@pytest.mark.scenario("""
    Given a new behandelaar who wants dashboard signals for zaken put on their name
    When the test admin starts 26 zaken with that behandelaar
    Then the dashboard's zaken on their name count 26, with 25 on the first page and 1 on the second
    And Mijn zaken counts 26, with 25 on the first page
""")
def test_dashboard_lists_count_more_than_a_page(
    zac: requests.Session,
    podiumd_env: Environment,
    urls: dict[str, str],
    openzaak: ApiClient,
    bpmn_parameters: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """ZAAK_OP_NAAM's totaal and Mijn zaken's totaal count every zaak; the pages split them by rows."""
    zac_url = urls["zac"]
    group = make_role_group(podiumd_env, registry, "behandelaar")
    username, password = make_group_member(podiumd_env, registry, group)
    user = zac_session(podiumd_env, username, password)
    save_signalering_setting(user, zac_url, {"type": ZAAK_OP_NAAM, "dashboard": True, "mail": False})
    started = set()
    for _ in range(ZAKEN):
        zaak = create_zaak(
            zac,
            zac_url,
            bpmn_parameters,
            omschrijving=registry.tagged("bpmn"),
            groep={"id": group, "naam": group},
            behandelaar={"id": username},
        )
        clean_up_zaak(zac, zac_url, openzaak, registry, zaak)
        started.add(zaak["identificatie"])

    wait_until(
        lambda: signalering_page(user, zac_url, ZAAK_OP_NAAM, rows=ROWS).get("totaal") == ZAKEN,
        timeout=INDEX_TIMEOUT,
        description=f"{ZAKEN} zaken on the dashboard list {ZAAK_OP_NAAM} of {username}",
    )
    pages = [signalering_page(user, zac_url, ZAAK_OP_NAAM, page, ROWS) for page in (0, 1)]
    assert [page.get("totaal") for page in pages] == [ZAKEN, ZAKEN]
    listed = [[str(zaak.get("identificatie")) for zaak in entries(page.get("resultaten"))] for page in pages]
    assert [len(identificaties) for identificaties in listed] == [ROWS, ZAKEN - ROWS]
    assert set(listed[0] + listed[1]) == started

    wait_until(
        lambda: search(user, zac_url, rows=ROWS, type="ZAAK", alleenMijnZaken=True).get("totaal") == ZAKEN,
        timeout=INDEX_TIMEOUT,
        description=f"{ZAKEN} zaken in Mijn zaken of {username}",
    )
    found = search(user, zac_url, rows=ROWS, type="ZAAK", alleenMijnZaken=True)
    assert len(entries(found.get("resultaten"))) == ROWS
