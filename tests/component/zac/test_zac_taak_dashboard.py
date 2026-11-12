"""ZAC's dashboard for a CMMN taak started for another user (signalering TAAK_OP_NAAM)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ZAC_ROLE_USERS
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import ADVIES_INTERN
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import is_taak_listed
from podiumd_tests.zac import read_taak
from podiumd_tests.zac import started_taak
from podiumd_tests.zac_signaleringen import signalering_taken
from podiumd_tests.zac_signaleringen import turn_signaleringen

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, taken-cmmn).",
    ),
    # Fixture zac_taken_zaaktype: one throwaway zaaktype per run, shared with test_zac_taken.py.
    pytest.mark.xdist_group("zac-taken-zaaktype"),
]


@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC, and a behandelaar who wants dashboard signals for taken on their name
    When the test admin starts Advies intern for that behandelaar
    Then the behandelaar's dashboard lists the taak among the taken on their name and in Mijn taken
    When the behandelaar opens the taak
    Then the dashboard no longer lists it among the taken on their name
""")
def test_taak_started_for_a_behandelaar_is_on_their_dashboard(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    behandeling: JsonObject,
    zac_group: str,
    registry: ResourceRegistry,
) -> None:
    """Starting a CMMN taak for another user signals TAAK_OP_NAAM to that user; reading the taak deletes it."""
    zac_url = urls["zac"]
    behandelaar = zac_as("behandelaar")
    turn_signaleringen(behandelaar, zac_url, registry, TAAK_OP_NAAM=True)
    naam = ZAC_ROLE_USERS["behandelaar"].username
    taak = started_taak(
        zac, zac_url, behandeling, ADVIES_INTERN, (zac_group, naam), taakdata={"vraag": "podiumd-tests vraag"}
    )
    wait_until(
        lambda: taak["id"] in signalering_taken(behandelaar, zac_url),
        timeout=INDEX_TIMEOUT,
        description=f"taak {taak['id']} on the dashboard of {naam}",
    )
    wait_until(
        lambda: is_taak_listed(behandelaar, zac_url, taak, alleenMijnTaken=True),
        timeout=LIST_TIMEOUT,
        description=f"taak {taak['id']} in Mijn taken of {naam}",
    )
    read_taak(behandelaar, zac_url, str(taak["id"]))
    assert taak["id"] not in signalering_taken(behandelaar, zac_url)
