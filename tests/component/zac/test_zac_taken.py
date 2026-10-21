"""ZAC's human task Aanvullende informatie on a zaak in intake: started, in Mijn taken, distributed and released.

Ported from ZAC's own e2e features taken-toevoegen and taken-verdelen-vrijgeven, through the REST API its UI calls.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import search

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

# ZAC starts the zaak's CMMN case, and runs list distributions, in the background.
TIMEOUT = 60


@pytest.fixture(name="taak")
def fixture_taak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    zac_group: str,
    need_bootstrap: Callable[..., None],
) -> JsonObject:
    """The task Aanvullende informatie, started on a new zaak for the test admin in its group, without a mail."""
    need_bootstrap("zac-aanvullende-informatie")
    zaak = zac_zaak()
    plan_items = f"{urls['zac']}/rest/planitems"

    def offered() -> JsonObject | None:
        found = get_entries(zac, f"{plan_items}/zaak/{zaak['uuid']}/humanTaskPlanItems")
        return next((p for p in found if p.get("formulierDefinitie") == "AANVULLENDE_INFORMATIE"), None)

    plan_item = wait_until(offered, timeout=TIMEOUT, description=f"Aanvullende informatie on {zaak['identificatie']}")
    body = {
        "planItemInstanceId": plan_item["id"],
        "groep": {"id": zac_group, "naam": zac_group},
        "medewerker": {"id": ADMIN.username, "naam": ADMIN.username},
        "taakdata": {},
        "taakStuurGegevens": {"sendMail": False},
    }
    expect_status(zac.post(f"{plan_items}/doHumanTaskPlanItem", json=body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    taken = get_entries(zac, f"{urls['zac']}/rest/taken/zaak/{zaak['uuid']}")
    return next(t for t in taken if t.get("formulierDefinitieId") == "AANVULLENDE_INFORMATIE")


def assignment(taak: JsonObject) -> tuple[object, object]:
    """(group id, behandelaar id) of a task."""
    return section(taak, "groep").get("id"), section(taak, "behandelaar").get("id")


@pytest.mark.source(
    "ZAC features/5-taken-toevoegen.feature",
    "Lacking information to finish the intake, Bob assigns an Aanvullende informatie task, which the assignee sees in Mijn taken.",
)
def test_started_task_is_in_mijn_taken(
    zac: requests.Session, urls: dict[str, str], taak: JsonObject, zac_group: str
) -> None:
    """The started task has the chosen group and behandelaar, and ZAC's Mijn taken lists it."""
    assert assignment(taak) == (zac_group, ADMIN.username)

    def listed() -> bool:
        found = search(
            zac, urls["zac"], type="TAAK", zoeken={"TAAK_ZAAK_ID": taak["zaakIdentificatie"]}, alleenMijnTaken=True
        )
        return any(r.get("id") == taak["id"] for r in entries(found["resultaten"]))

    wait_until(listed, timeout=TIMEOUT, description=f"task {taak['id']} in Mijn taken")


@pytest.mark.source(
    "ZAC features/7-taken-verdelen-vrijgeven.feature",
    "Bob assigns selected taken from the werkvoorraad to a group and user, and releases them.",
)
def test_taken_from_the_list_are_released_and_assigned(
    zac: requests.Session, urls: dict[str, str], taak: JsonObject, zac_group: str
) -> None:
    """Vrijgeven takes the behandelaar away from the selected task; verdelen gives it back."""
    taken = f"{urls['zac']}/rest/taken"
    selected = [{"taakId": taak["id"], "zaakUuid": taak["zaakUuid"]}]

    def is_(wanted: tuple[object, object]) -> bool:
        return assignment(expect_status(zac.get(f"{taken}/{taak['id']}"), HTTPStatus.OK).json()) == wanted

    expect_status(zac.put(f"{taken}/lijst/vrijgeven", json={"taken": selected, "reden": "test"}), 200, 204)
    wait_until(lambda: is_((zac_group, None)), timeout=TIMEOUT, description=f"task {taak['id']} vrijgegeven")
    body = {"taken": selected, "groepId": zac_group, "behandelaarGebruikersnaam": ADMIN.username, "reden": "test"}
    expect_status(zac.put(f"{taken}/lijst/verdelen", json=body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    wait_until(lambda: is_((zac_group, ADMIN.username)), timeout=TIMEOUT, description=f"task {taak['id']} verdeeld")
