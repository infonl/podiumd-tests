"""ZAC's assignment of zaken to a group and behandelaar, one at a time and from the werkvoorraad list.

Ported from ZAC's own e2e features zaken-verdelen-vrijgeven and bpmn (toekennen), through the REST API its UI calls.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import read_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

# ZAC assigns and releases list selections in a background job.
LIST_TIMEOUT = 60


def assignment(zaak: JsonObject) -> tuple[object, object]:
    """(group id, behandelaar id) of ZAC's view of a zaak."""
    return section(zaak, "groep").get("id"), section(zaak, "behandelaar").get("id")


@pytest.mark.source("ZAC features/9-bpmn.feature", "Bob changes the group and user a zaak is assigned to.")
def test_zaak_is_assigned_to_a_group_and_behandelaar(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], zac_group: str
) -> None:
    """Toekennen gives the zaak the chosen group and behandelaar."""
    zaak = zac_zaak()
    body = {
        "zaakUUID": zaak["uuid"],
        "groepId": zac_group,
        "behandelaarGebruikersnaam": ADMIN.username,
        "reden": "test",
    }
    assigned = expect_status(zac.patch(f"{urls['zac']}/rest/zaken/toekennen", json=body), HTTPStatus.OK).json()
    assert assignment(assigned) == (zac_group, ADMIN.username)


@pytest.mark.source(
    "ZAC features/6-zaken-verdelen-vrijgeven.feature",
    "Bob assigns selected zaken from the werkvoorraad to a group and user, and releases them.",
)
def test_zaken_from_the_list_are_assigned_and_released(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], zac_group: str
) -> None:
    """Verdelen gives the selected zaken the group and behandelaar; vrijgeven takes the behandelaar away again."""
    uuids = [str(zac_zaak()["uuid"]), str(zac_zaak()["uuid"])]
    zaken = f"{urls['zac']}/rest/zaken/lijst"

    def all_are(wanted: tuple[object, object]) -> bool:
        return all(assignment(read_zaak(zac, urls["zac"], u)) == wanted for u in uuids)

    body = {"uuids": uuids, "groepId": zac_group, "behandelaarGebruikersnaam": ADMIN.username, "reden": "test"}
    expect_status(zac.put(f"{zaken}/verdelen", json=body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    wait_until(lambda: all_are((zac_group, ADMIN.username)), timeout=LIST_TIMEOUT, description="zaken verdeeld")
    expect_status(zac.put(f"{zaken}/vrijgeven", json={"uuids": uuids, "reden": "test"}), 200, 204)
    wait_until(lambda: all_are((zac_group, None)), timeout=LIST_TIMEOUT, description="zaken vrijgegeven")
