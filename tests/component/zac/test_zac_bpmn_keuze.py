"""A BPMN zaak handled by its own process: opgeschort, hervat, verlengd, its statuses and taken, from task Keuze."""

from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import EINDSTATUS
from podiumd_tests.bootstrap.bpmn import IN_BEHANDELING
from podiumd_tests.bootstrap.bpmn import KEUZE
from podiumd_tests.bootstrap.bpmn import SUMMARY
from podiumd_tests.bootstrap.bpmn import TERMIJN
from podiumd_tests.bootstrap.bpmn import VORIGE
from podiumd_tests.bootstrap.bpmn import complete_keuze
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import assignment
from podiumd_tests.zac import attribuut_historie
from podiumd_tests.zac import group_members
from podiumd_tests.zac import moved_dates
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import statustypen
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import zaak_historie
from podiumd_tests.zac_beheer import referentietabel
from podiumd_tests.zac_taken import complete_task
from podiumd_tests.zac_taken import open_task
from podiumd_tests.zac_taken import read_taak

if TYPE_CHECKING:
    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "pabc", "keycloak"),
    pytest.mark.source(
        "external Dimpact-Samenwerking/zaakafhandelcomponent-configuratie end-to-end-testproces (E2E)",
        "The ZAC steps of its Keuze scherm, reimplemented on podiumd-tests' process (the source has no licence).",
    ),
]

DAYS = 3
# A statustype of the BPMN test zaaktype before In behandeling.
INGEDIEND = "Ingediend"


def _toelichtingen(zac: requests.Session, zac_url: str, zaak: JsonObject) -> set[object]:
    return {line.get("toelichting") for line in zaak_historie(zac, zac_url, zaak)}


def _formio_moment(day: date, at: time) -> str:
    """The value a Form.io datetime field submits: local time with its UTC offset."""
    return datetime.combine(day, at).astimezone().isoformat()


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC at its Keuze taak
    When the behandelaar chooses opschorten for 3 days with a reden
    Then the process suspends the zaak: its streefdatum and fatale datum are 3 days later
    When the behandelaar chooses hervatten the same day with a reden
    Then the process resumes the zaak: it has its dates back
    And the historie shows the opschorting and the hervatting with their redenen
""")
def test_process_schort_the_zaak_op_and_hervat_it(
    zac: requests.Session, urls: dict[str, str], keuze_zaak: JsonObject
) -> None:
    """SuspendZaakDelegate and ResumeZaakDelegate, with the days and redenen of the form."""
    zac_url, uuid = urls["zac"], str(keuze_zaak["uuid"])
    complete_keuze(zac, zac_url, keuze_zaak, "opschorten", ptestDagen=DAYS, ptestReden="podiumd-tests op")
    opgeschort = read_zaak(zac, zac_url, uuid)
    assert (opgeschort["isOpgeschort"], moved_dates(opgeschort, 0)) == (True, moved_dates(keuze_zaak, DAYS))
    complete_keuze(zac, zac_url, keuze_zaak, "hervatten", ptestReden="podiumd-tests her")
    hervat = read_zaak(zac, zac_url, uuid)
    assert (hervat["isOpgeschort"], moved_dates(hervat, 0)) == (False, moved_dates(keuze_zaak, 0))
    toelichtingen = _toelichtingen(zac, zac_url, keuze_zaak)
    assert {"Opschorting: podiumd-tests op", "Hervatting: podiumd-tests her"} <= toelichtingen, toelichtingen


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC whose process suspended it for 3 days today
    When the behandelaar chooses hervatten with tomorrow as hervatdatum
    Then the zaak is no longer opgeschort
    And its fatale datum is 1 day later than before the opschorting: only the day it was opgeschort counts
""")
def test_process_hervat_the_zaak_on_a_hervatdatum(
    zac: requests.Session, urls: dict[str, str], keuze_zaak: JsonObject
) -> None:
    """ResumeZaakDelegate with hervattenDatum moves the dates by the whole days between opschorting and that date."""
    zac_url = urls["zac"]
    complete_keuze(zac, zac_url, keuze_zaak, "opschorten", ptestDagen=DAYS, ptestReden="podiumd-tests op")
    morgen = _formio_moment(date.today() + timedelta(days=1), time(23, 59, 59))  # noqa: DTZ011  # ZAC's local date
    complete_keuze(zac, zac_url, keuze_zaak, "hervatten", ptestReden="podiumd-tests her", ptestHervatDatum=morgen)
    hervat = read_zaak(zac, zac_url, str(keuze_zaak["uuid"]))
    assert (hervat["isOpgeschort"], moved_dates(hervat, 0)) == (False, moved_dates(keuze_zaak, 1))


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC at its Keuze taak
    When the behandelaar chooses a taak Termijn with a fatale datum 5 days from now
    Then the taak Termijn is open beside a new Keuze taak, with that fatale datum
    When the behandelaar chooses verlengen by 3 days with a reden, its open taken too
    Then the process extends the zaak: it is verlengd, its dates are 3 days later and the historie shows the reden
    And the taak Termijn's fatale datum is 3 days later
""")
def test_process_verlengt_the_zaak_and_its_taak_with_a_fatale_datum(
    zac: requests.Session, urls: dict[str, str], keuze_zaak: JsonObject
) -> None:
    """A user task's dueDate from a form field; ExtendZaakDelegate with takenVerlengen moves it with the zaak."""
    zac_url, uuid = urls["zac"], str(keuze_zaak["uuid"])
    fatale_datum = date.today() + timedelta(days=5)  # noqa: DTZ011  # ZAC's local date
    complete_keuze(zac, zac_url, keuze_zaak, "termijn", ptestTaakFataleDatum=_formio_moment(fatale_datum, time()))
    termijn = open_task(zac, zac_url, uuid, TERMIJN)
    assert termijn.get("fataledatum") == fatale_datum.isoformat()
    reden = "podiumd-tests verlenging"
    complete_keuze(zac, zac_url, keuze_zaak, "verlengen", ptestDagen=DAYS, ptestReden=reden, ptestTakenVerlengen=True)
    verlengd = read_zaak(zac, zac_url, uuid)
    assert (verlengd["isVerlengd"], moved_dates(verlengd, 0)) == (True, moved_dates(keuze_zaak, DAYS))
    assert f"Verlenging: {reden}" in _toelichtingen(zac, zac_url, keuze_zaak)
    moved = (fatale_datum + timedelta(days=DAYS)).isoformat()
    assert read_taak(zac, zac_url, str(termijn["id"])).get("fataledatum") == moved


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC whose process set the status In behandeling after the intake
    When the behandelaar chooses the status Ingediend, then In behandeling, from the statuses ZAC offers
    And then chooses to finish, and confirms the summary
    Then the historie shows In behandeling, Ingediend, In behandeling and the end status, in that order
""")
def test_process_sets_the_statuses_chosen_in_its_taken(
    zac: requests.Session, urls: dict[str, str], keuze_zaak: JsonObject
) -> None:
    """UpdateZaakJavaDelegate with the statustype of a ZAC_status select, at several points of the process."""
    zac_url = urls["zac"]
    offered = {str(statustype.get("naam")) for statustype in statustypen(zac, zac_url, keuze_zaak)}
    assert {INGEDIEND, IN_BEHANDELING} <= offered, offered
    for status in (INGEDIEND, IN_BEHANDELING):
        complete_keuze(zac, zac_url, keuze_zaak, "status", ptestStatus=status)
    complete_keuze(zac, zac_url, keuze_zaak, "afronden")
    complete_task(zac, zac_url, open_task(zac, zac_url, str(keuze_zaak["uuid"]), SUMMARY), {})
    # Newest first; ZAC also logs each change of the zaak's status URL.
    historie = attribuut_historie(zac, zac_url, keuze_zaak, "status")
    statussen = [nieuw for _, nieuw, _ in historie if not str(nieuw).startswith("http")]
    assert statussen == [EINDSTATUS, IN_BEHANDELING, INGEDIEND, IN_BEHANDELING]


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC at its Keuze taak, whose form has a select of a ZAC referentietabel
    When the behandelaar picks a value ZAC lists for that referentietabel and chooses to finish
    Then the summary taak has the picked value in its zaakdata
""")
def test_keuze_select_of_a_referentietabel_keeps_the_picked_value(
    zac: requests.Session, urls: dict[str, str], keuze_zaak: JsonObject
) -> None:
    """ZAC serves the form's ReferenceTable_Code; the select submits the value's id (valueProperty id)."""
    zac_url, uuid = urls["zac"], str(keuze_zaak["uuid"])
    keuze = open_task(zac, zac_url, uuid, KEUZE)
    components = entries(section(keuze, "formioFormulier").get("components"))
    select = next(component for component in components if component.get("key") == "ptestKanaal")
    code = str(section(select, "properties").get("ReferenceTable_Code"))
    waarde = entries(referentietabel(zac, zac_url, code).get("values"))[-1]
    complete_task(zac, zac_url, keuze, {"ptestActie": "afronden", "ptestKanaal": waarde["id"]})
    summary = read_taak(zac, zac_url, str(open_task(zac, zac_url, uuid, SUMMARY)["id"]))
    assert section(summary, "taakdata").get("ptestKanaal") == waarde["id"]


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC at its Keuze taak for the test admin
    When the zaak is assigned to another behandelaar of the group
    And the test admin chooses a taak for the previous behandelaar
    Then that taak is for the test admin, who did the Keuze taak, not for the zaak's new behandelaar
    When the test admin completes it
    Then the next Keuze taak is for the zaak's new behandelaar
""")
def test_process_assigns_a_taak_to_the_previous_behandelaar(
    zac: requests.Session, urls: dict[str, str], keuze_zaak: JsonObject, zac_group: str
) -> None:
    """taken:behandelaar('keuze') and taken:groep('keuze'): the last Keuze taak's assignment."""
    zac_url, uuid = urls["zac"], str(keuze_zaak["uuid"])
    others = sorted(group_members(zac, zac_url, zac_group) - {ADMIN.username})
    if not others:
        pytest.skip(f"group {zac_group} has no member but {ADMIN.username}: add a Keycloak user to it")
    expect_status(toekennen(zac, zac_url, keuze_zaak, zac_group, others[0]), HTTPStatus.OK)
    complete_keuze(zac, zac_url, keuze_zaak, "vorige")
    vorige = open_task(zac, zac_url, uuid, VORIGE)
    assert assignment(vorige) == (zac_group, ADMIN.username)
    complete_task(zac, zac_url, vorige, {})
    assert assignment(open_task(zac, zac_url, uuid, KEUZE)) == (zac_group, others[0])
