"""ZAC's human task Aanvullende informatie on a zaak in intake: started, in Mijn taken, distributed and released.

Ported from ZAC's own e2e features taken-toevoegen and taken-verdelen-vrijgeven, through the REST API its UI calls.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import search

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

# ZAC's statustype omschrijving while a task Aanvullende informatie is open (ConfigurationService).
WAITING = "Wacht op aanvullende informatie"

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

# ZAC starts the zaak's CMMN case, and runs list distributions, in the background.
TIMEOUT = 60
SUSPENSION_DAYS = 7


@pytest.fixture(name="start_taak")
def fixture_start_taak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_group: str,
    need_bootstrap: Callable[..., None],
) -> Callable[..., JsonObject]:
    """Start the task Aanvullende informatie on a zaak for the test admin in its group, without a mail.

    fields: more of ZAC's RESTHumanTaskData, e.g. taakdata zaakOpschorten with a fataledatum.
    """
    need_bootstrap("zac-aanvullende-informatie")
    plan_items = f"{urls['zac']}/rest/planitems"

    def start(zaak: JsonObject, **fields: object) -> JsonObject:
        def offered() -> JsonObject | None:
            found = get_entries(zac, f"{plan_items}/zaak/{zaak['uuid']}/humanTaskPlanItems")
            return next((p for p in found if p.get("formulierDefinitie") == "AANVULLENDE_INFORMATIE"), None)

        plan_item = wait_until(
            offered, timeout=TIMEOUT, description=f"Aanvullende informatie on {zaak['identificatie']}"
        )
        body = {
            "planItemInstanceId": plan_item["id"],
            "groep": {"id": zac_group, "naam": zac_group},
            "medewerker": {"id": ADMIN.username, "naam": ADMIN.username},
            "taakdata": {},
            "taakStuurGegevens": {"sendMail": False},
            **fields,
        }
        expect_status(zac.post(f"{plan_items}/doHumanTaskPlanItem", json=body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
        taken = get_entries(zac, f"{urls['zac']}/rest/taken/zaak/{zaak['uuid']}")
        return next(t for t in taken if t.get("formulierDefinitieId") == "AANVULLENDE_INFORMATIE")

    return start


@pytest.fixture(name="taak")
def fixture_taak(zac_zaak: Callable[..., JsonObject], start_taak: Callable[..., JsonObject]) -> JsonObject:
    """The task Aanvullende informatie, started on a new zaak."""
    return start_taak(zac_zaak())


def assignment(taak: JsonObject) -> tuple[object, object]:
    """(group id, behandelaar id) of a task."""
    return section(taak, "groep").get("id"), section(taak, "behandelaar").get("id")


@pytest.mark.source(
    "ZAC features/5-taken-toevoegen.feature",
    "Lacking information to finish the intake, Bob assigns an Aanvullende informatie task, which the assignee sees in Mijn taken.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar starts the taak Aanvullende informatie for a group and a behandelaar
    Then the taak has that group and behandelaar
    And the taak is listed in Mijn taken
""")
def test_started_task_is_in_mijn_taken(
    zac: requests.Session, urls: dict[str, str], taak: JsonObject, zac_group: str
) -> None:
    """The started task has the chosen group and behandelaar, and ZAC's Mijn taken lists it."""
    assert assignment(taak) == (zac_group, ADMIN.username)

    def is_listed() -> bool:
        found = search(
            zac, urls["zac"], type="TAAK", zoeken={"TAAK_ZAAK_ID": taak["zaakIdentificatie"]}, alleenMijnTaken=True
        )
        return any(r.get("id") == taak["id"] for r in entries(found["resultaten"]))

    wait_until(is_listed, timeout=TIMEOUT, description=f"task {taak['id']} in Mijn taken")


@pytest.mark.source(
    "ZAC features/5-taken-toevoegen.feature",
    "When Intake lacks information, a task Aanvullende informatie gives the zaak status 'Wacht op aanvullende informatie'.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar starts the taak Aanvullende informatie on it
    Then the zaak has the status Wacht op aanvullende informatie
""")
def test_aanvullende_informatie_gives_the_zaak_its_waiting_status(
    zac: requests.Session, urls: dict[str, str], taak: JsonObject
) -> None:
    """ZAC sets the zaak's status when the task Aanvullende informatie starts (AanvullendeInformatieTaskListener)."""

    def status() -> str | None:
        naam = section(read_zaak(zac, urls["zac"], str(taak["zaakUuid"])), "status").get("naam")
        return str(naam) if naam == WAITING else None

    wait_until(status, timeout=TIMEOUT, description=f"status {WAITING!r} on {taak['zaakIdentificatie']}")


@pytest.mark.source(
    "ZAC features/7-taken-verdelen-vrijgeven.feature",
    "Bob assigns selected taken from the werkvoorraad to a group and user, and releases them.",
)
@pytest.mark.scenario("""
    Given a taak Aanvullende informatie on a zaak in ZAC, assigned to a behandelaar
    When the behandelaar releases the taak from the list
    Then the taak keeps its group but has no behandelaar
    When the behandelaar assigns the taak from the list to the group and a behandelaar
    Then the taak has that group and behandelaar again
""")
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


@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar starts the taak Aanvullende informatie with opschorten until its fatale datum
    Then the zaak is opgeschort, and its uiterlijke einddatum afdoening moved by those days
    When the behandelaar completes the taak with hervatten
    Then the zaak is no longer opgeschort, and its date moved back by the days not used
""")
def test_aanvullende_informatie_with_opschorten_suspends_until_hervatten(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    start_taak: Callable[..., JsonObject],
) -> None:
    """zaakOpschorten suspends the zaak until the task's fatale datum; zaakHervatten on completion resumes it."""
    zaak = zac_zaak()
    original = date.fromisoformat(str(zaak["uiterlijkeEinddatumAfdoening"]))
    fataledatum = date.today() + timedelta(days=SUSPENSION_DAYS)  # noqa: DTZ011  # ZAC's local date
    taak = start_taak(zaak, fataledatum=fataledatum.isoformat(), taakdata={"zaakOpschorten": "true"})
    opgeschort = read_zaak(zac, urls["zac"], str(zaak["uuid"]))
    assert opgeschort["isOpgeschort"] is True
    moved = date.fromisoformat(str(opgeschort["uiterlijkeEinddatumAfdoening"]))
    assert moved == original + timedelta(days=SUSPENSION_DAYS)

    body = {**taak, "taakdata": {**section(taak, "taakdata"), "zaakHervatten": "true"}}
    expect_status(zac.patch(f"{urls['zac']}/rest/taken/complete", json=body), HTTPStatus.OK)
    hervat = read_zaak(zac, urls["zac"], str(zaak["uuid"]))
    assert hervat["isOpgeschort"] is False
    assert hervat["uiterlijkeEinddatumAfdoening"] == original.isoformat()
