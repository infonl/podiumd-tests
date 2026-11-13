"""A BPMN zaak handled beside its process: opgeschort, verlengd, edited and assigned, and its zaakdata."""

from __future__ import annotations

from datetime import date
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import HARDCODED
from podiumd_tests.bootstrap.bpmn import HARDCODED_TO
from podiumd_tests.bootstrap.bpmn import INHERITED
from podiumd_tests.bootstrap.bpmn import SELECT
from podiumd_tests.bootstrap.bpmn import SIGN
from podiumd_tests.bootstrap.bpmn import SUMMARY
from podiumd_tests.bootstrap.bpmn import TOEWIJZING
from podiumd_tests.bootstrap.bpmn import complete_intake
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.zac import assignment
from podiumd_tests.zac import group_members
from podiumd_tests.zac import hervatten
from podiumd_tests.zac import moved_dates
from podiumd_tests.zac import opschorten
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import verlengen
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac import zaak_historie
from podiumd_tests.zac_beheer import communicatiekanalen
from podiumd_tests.zac_taken import complete_task
from podiumd_tests.zac_taken import open_task
from podiumd_tests.zac_taken import read_taak

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "pabc", "keycloak"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, bpmn).",
    ),
]

DAYS = 3
# A form field of no task: ZAC keeps every submitted field as zaakdata.
BELANGHEBBENDE = "ptestBelanghebbende"
# BSNs of the BRP test set.
BSN, ANDER_BSN = "999993653", "999990639"


def _taak(zac: requests.Session, zac_url: str, zaak: JsonObject, name: str) -> JsonObject:
    """The zaak's open task of this name as ZAC opens it: with the zaakdata in its taakdata."""
    return read_taak(zac, zac_url, str(open_task(zac, zac_url, str(zaak["uuid"]), name)["id"]))


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC
    When the behandelaar suspends it for 3 days with a reden
    Then the zaak is opgeschort, its fatale datum is 3 days later, and the historie shows the opschorting
    When the behandelaar resumes it the same day
    Then the zaak is no longer opgeschort and has its fatale datum back
    When the behandelaar extends it by 3 days
    Then the zaak is verlengd and its fatale datum is 3 days later
""")
def test_bpmn_zaak_is_opgeschort_hervat_and_verlengd(
    zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject
) -> None:
    """Opschorten, hervatten and verlengen do not depend on the zaak's CMMN case."""
    zac_url, uuid = urls["zac"], str(bpmn_zaak["uuid"])
    opgeschort = expect_status(opschorten(zac, zac_url, bpmn_zaak, DAYS, "podiumd-tests op"), HTTPStatus.OK).json()
    assert (opgeschort["isOpgeschort"], moved_dates(opgeschort, 0)) == (True, moved_dates(bpmn_zaak, DAYS))
    historie = {
        (line.get("attribuutLabel"), line.get("toelichting")) for line in zaak_historie(zac, zac_url, bpmn_zaak)
    }
    assert ("uiterlijkeEinddatumAfdoening", "Opschorting: podiumd-tests op") in historie, historie

    expect_status(hervatten(zac, zac_url, bpmn_zaak), HTTPStatus.OK)
    hervat = read_zaak(zac, zac_url, uuid)
    assert (hervat["isOpgeschort"], moved_dates(hervat, 0)) == (False, moved_dates(bpmn_zaak, 0))

    expect_status(verlengen(zac, zac_url, hervat, DAYS), HTTPStatus.OK)
    verlengd = read_zaak(zac, zac_url, uuid)
    assert (verlengd["isVerlengd"], moved_dates(verlengd, 0)) == (True, moved_dates(bpmn_zaak, DAYS))


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC whose intake form named a belanghebbende
    When the behandelaar changes the zaak's omschrijving and communicatiekanaal
    Then the zaak has both changes
    And the next taak's zaakdata hold the new communicatiekanaal and the belanghebbende
    And its form shows the zaak's fatale datum as dd-mm-jjjj, its behandelaar and its new communicatiekanaal
    When the behandelaar submits that taak with another belanghebbende
    Then the taak after it has that other belanghebbende in its zaakdata
""")
def test_bpmn_zaakdata_follow_the_zaak_and_its_taken(
    zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject, zac_group: str, registry: ResourceRegistry
) -> None:
    """A zaak edit sets zaakdata zaakCommunicatiekanaal; a submitted form field becomes zaakdata for later taken.

    ZAC fills a form field's defaultValue ZAAK:*, TAAK:* or :<zaakdata> when it reads the taak.
    """
    zac_url = urls["zac"]
    complete_intake(zac, zac_url, bpmn_zaak, (zac_group, ADMIN.username), **{BELANGHEBBENDE: BSN})
    kanaal = next(kanaal for kanaal in communicatiekanalen(zac, zac_url) if kanaal != bpmn_zaak["communicatiekanaal"])
    omschrijving = registry.tagged("bpmn-gewijzigd")
    expect_status(
        wijzig_zaak(zac, zac_url, bpmn_zaak, omschrijving=omschrijving, communicatiekanaal=kanaal), HTTPStatus.OK
    )
    gewijzigd = read_zaak(zac, zac_url, str(bpmn_zaak["uuid"]))
    assert (gewijzigd["omschrijving"], gewijzigd["communicatiekanaal"]) == (omschrijving, kanaal)

    select = _taak(zac, zac_url, bpmn_zaak, SELECT)
    zaakdata = section(select, "taakdata")
    assert (zaakdata.get("zaakCommunicatiekanaal"), zaakdata.get(BELANGHEBBENDE)) == (kanaal, BSN)
    fatale_datum = date.fromisoformat(str(gewijzigd["uiterlijkeEinddatumAfdoening"])).strftime("%d-%m-%Y")
    defaults = {
        str(component.get("key")): component.get("defaultValue")
        for component in entries(section(select, "formioFormulier").get("components"))
        if "defaultValue" in component
    }
    assert defaults == {
        "ptestZaakFataleDatum": fatale_datum,
        "ptestZaakBehandelaar": ADMIN.username,
        "ptestCommunicatiekanaal": kanaal,
    }
    complete_task(zac, zac_url, select, {"ZAAK_Documenten_Ondertekenen_Selectie": [], BELANGHEBBENDE: ANDER_BSN})
    assert section(_taak(zac, zac_url, bpmn_zaak, SIGN), "taakdata").get(BELANGHEBBENDE) == ANDER_BSN


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC past its intake, with the document selection open for the test admin
    When the behandelaar assigns the zaak to another behandelaar of the group
    And completes the document selection
    Then the next taak, signing, is for the zaak's group and the other behandelaar
""")
def test_next_bpmn_taak_follows_the_zaaks_new_behandelaar(
    zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject, zac_group: str
) -> None:
    """Toekennen sets the process's zaakGroep and zaakBehandelaar, which the next user task's assignment reads."""
    zac_url = urls["zac"]
    others = sorted(group_members(zac, zac_url, zac_group) - {ADMIN.username})
    if not others:
        pytest.skip(f"group {zac_group} has no member but {ADMIN.username}: add a Keycloak user to it")
    naam = others[0]
    complete_intake(zac, zac_url, bpmn_zaak, (zac_group, ADMIN.username))
    expect_status(toekennen(zac, zac_url, bpmn_zaak, zac_group, naam), HTTPStatus.OK)
    select = open_task(zac, zac_url, str(bpmn_zaak["uuid"]), SELECT)
    complete_task(zac, zac_url, select, {"ZAAK_Documenten_Ondertekenen_Selectie": []})
    sign = open_task(zac, zac_url, str(bpmn_zaak["uuid"]), SIGN)
    assert (section(sign, "groep").get("id"), section(sign, "behandelaar").get("id")) == (zac_group, naam)


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC
    When the behandelaar submits the intake for a new group without behandelaar, choosing the assignment variants
    Then the zaak has that group and no behandelaar
    And the next taak has the group and behandelaar the process names for it, not the zaak's
    When the behandelaar completes that taak
    Then the next taak takes the group and behandelaar of the taak before it
    When the behandelaar assigns the zaak to their own group and themselves, and completes that taak
    Then the summary taak has the zaak's new group and behandelaar
""")
def test_bpmn_taken_take_a_fixed_an_inherited_and_the_zaaks_new_assignment(
    zac: requests.Session,
    podiumd_env: Environment,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    registry: ResourceRegistry,
) -> None:
    """A user task's literal candidates, taken:groep/taken:behandelaar of the previous task, and zaakGroep after toekennen."""
    zac_url, uuid = urls["zac"], str(bpmn_zaak["uuid"])
    keuze = make_role_group(podiumd_env, registry, "behandelaar")
    complete_intake(zac, zac_url, bpmn_zaak, (keuze, ""), **{TOEWIJZING: True})
    assert assignment(read_zaak(zac, zac_url, uuid)) == (keuze, None)
    hardcoded = open_task(zac, zac_url, uuid, HARDCODED)
    assert assignment(hardcoded) == HARDCODED_TO
    complete_task(zac, zac_url, hardcoded, {})
    assert assignment(open_task(zac, zac_url, uuid, INHERITED)) == HARDCODED_TO
    expect_status(toekennen(zac, zac_url, bpmn_zaak, zac_group, ADMIN.username), HTTPStatus.OK)
    complete_task(zac, zac_url, open_task(zac, zac_url, uuid, INHERITED), {})
    assert assignment(open_task(zac, zac_url, uuid, SUMMARY)) == (zac_group, ADMIN.username)
