"""ZAC's dashboard (signalering TAAK_OP_NAAM) and Mijn taken for a CMMN taak of another user."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import ZAC_ROLE_USERS
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import assignment
from podiumd_tests.zac import is_taak_listed
from podiumd_tests.zac_signaleringen import signalering_taken
from podiumd_tests.zac_signaleringen import turn_signaleringen
from podiumd_tests.zac_taken import ADVIES_INTERN
from podiumd_tests.zac_taken import read_taak
from podiumd_tests.zac_taken import started_taak
from podiumd_tests.zac_taken import verdelen_taken
from podiumd_tests.zac_taken import vrijgeven_taken

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


@pytest.mark.source(
    "ZAC features/7-taken-verdelen-vrijgeven.feature",
    "Bob assigns selected taken from the werkvoorraad to a group and user, and releases them.",
)
@pytest.mark.scenario("""
    Given a taak Aanvullende informatie on a zaak in ZAC, assigned to the test admin
    When the admin releases the taak from the list
    Then the taak keeps its group but has no behandelaar, and leaves the admin's Mijn taken
    When the admin assigns the taak from the list to the group and another behandelaar
    Then the taak has that group and behandelaar, and is in that behandelaar's Mijn taken
""")
def test_taken_from_the_list_are_released_and_assigned(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    taak: JsonObject,
    zac_group: str,
) -> None:
    """Vrijgeven takes the behandelaar away from the selected task; verdelen gives it a new one, in their Mijn taken."""
    zac_url = urls["zac"]
    behandelaar = zac_as("behandelaar")
    naam = ZAC_ROLE_USERS["behandelaar"].username

    def is_(wanted: tuple[object, object]) -> bool:
        return assignment(read_taak(zac, zac_url, str(taak["id"]))) == wanted

    expect_status(vrijgeven_taken(zac, zac_url, [taak]), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    wait_until(lambda: is_((zac_group, None)), timeout=LIST_TIMEOUT, description=f"task {taak['id']} vrijgegeven")
    wait_until(
        lambda: not is_taak_listed(zac, zac_url, taak, alleenMijnTaken=True),
        timeout=LIST_TIMEOUT,
        description=f"task {taak['id']} out of Mijn taken of {ADMIN.username}",
    )
    expect_status(verdelen_taken(zac, zac_url, [taak], zac_group, naam), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    wait_until(lambda: is_((zac_group, naam)), timeout=LIST_TIMEOUT, description=f"task {taak['id']} verdeeld")
    wait_until(
        lambda: is_taak_listed(behandelaar, zac_url, taak, alleenMijnTaken=True),
        timeout=LIST_TIMEOUT,
        description=f"task {taak['id']} in Mijn taken of {naam}",
    )
