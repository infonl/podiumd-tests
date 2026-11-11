"""ZAC's assignment of zaken to a group and behandelaar, one at a time and from the werkvoorraad list.

Ported from ZAC's own e2e features zaken-verdelen-vrijgeven and bpmn (toekennen), through the REST API its UI calls.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import assignment
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import verdelen
from podiumd_tests.zac import vrijgeven

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]


@pytest.mark.source("ZAC features/9-bpmn.feature", "Bob changes the group and user a zaak is assigned to.")
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar assigns the zaak to a group and a behandelaar
    Then the zaak has that group and behandelaar
""")
def test_zaak_is_assigned_to_a_group_and_behandelaar(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], zac_group: str
) -> None:
    """Toekennen gives the zaak the chosen group and behandelaar."""
    zaak = zac_zaak()
    assigned = expect_status(toekennen(zac, urls["zac"], zaak, zac_group, ADMIN.username), HTTPStatus.OK).json()
    assert assignment(assigned) == (zac_group, ADMIN.username)


@pytest.mark.source(
    "ZAC features/6-zaken-verdelen-vrijgeven.feature",
    "Bob assigns selected zaken from the werkvoorraad to a group and user, and releases them.",
)
@pytest.mark.scenario("""
    Given two zaken in ZAC
    When the behandelaar assigns both from the werkvoorraad to a group and a behandelaar
    Then both zaken have that group and behandelaar
    When the behandelaar releases both zaken
    Then both zaken keep the group but have no behandelaar
""")
def test_zaken_from_the_list_are_assigned_and_released(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], zac_group: str
) -> None:
    """Verdelen gives the selected zaken the group and behandelaar; vrijgeven takes the behandelaar away again."""
    uuids = [str(zac_zaak()["uuid"]), str(zac_zaak()["uuid"])]

    def are_all(wanted: tuple[object, object]) -> bool:
        return all(assignment(read_zaak(zac, urls["zac"], u)) == wanted for u in uuids)

    expect_status(verdelen(zac, urls["zac"], uuids, zac_group, ADMIN.username), HTTPStatus.NO_CONTENT)
    wait_until(lambda: are_all((zac_group, ADMIN.username)), timeout=LIST_TIMEOUT, description="zaken verdeeld")
    expect_status(vrijgeven(zac, urls["zac"], uuids), HTTPStatus.NO_CONTENT)
    wait_until(lambda: are_all((zac_group, None)), timeout=LIST_TIMEOUT, description="zaken vrijgegeven")


@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md,"
    " zoeken-werklijsten-dashboard): verdelen to a group without behandelaar.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC assigned to the test admin and the admin's group
    When the coordinator assigns it from the werkvoorraad to another group, without a behandelaar
    Then the zaak has that group and no behandelaar
""")
def test_zaak_verdeeld_to_a_group_alone_loses_its_behandelaar(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    zac_group: str,
    zac_parameters: JsonObject,
) -> None:
    """Verdelen with a group and no behandelaar removes the behandelaar's rol (ZaakService.changeBehandelaar)."""
    groep = str(zac_parameters["defaultGroepId"])
    if groep == zac_group:
        pytest.skip(f"the zaaktype's default group is the test admin's group {groep}")
    zaak = zac_zaak()
    expect_status(toekennen(zac, urls["zac"], zaak, zac_group, ADMIN.username), HTTPStatus.OK)
    expect_status(verdelen(zac, urls["zac"], [str(zaak["uuid"])], groep, None), HTTPStatus.NO_CONTENT)
    wait_until(
        lambda: assignment(read_zaak(zac, urls["zac"], str(zaak["uuid"]))) == (groep, None),
        timeout=LIST_TIMEOUT,
        description=f"zaak {zaak['identificatie']} verdeeld to {groep}",
    )
