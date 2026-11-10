"""ZAC's BPMN zaken: a zaak of a zaaktype with a BPMN process, through its task forms to its end.

Ported from ZAC's src/e2e/features/9-bpmn.feature, on podiumd-tests' own process (bootstrap step
zac-bpmn-process): intake that assigns the zaak, select and sign documents, summary that closes the zaak.
The feature's SmartDocuments step is left out: no environment has SmartDocuments.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import bpmn_zaaktype
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.names import BPMN_ZAAKTYPE
from podiumd_tests.bootstrap.names import ZAC_APPLICATION_ROLES
from podiumd_tests.bootstrap.names import ZAC_FUNCTIONAL_ROLE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.pabc import decide
from podiumd_tests.pabc import mapped_application_roles
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.zac import complete_task
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import open_task
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import wait_in_werkvoorraad

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "pabc", "keycloak")]

FEATURE = "ZAC features/9-bpmn.feature"
# The process's tasks (src/podiumd_tests/bpmn/ptestBpmnProcess.bpmn) and the test zaaktype's last statustype.
INTAKE, SELECT, SIGN, SUMMARY = "Intake", "Select documents to sign", "Sign the selected documents", "Summary"
EINDSTATUS = "Afgehandeld"


@pytest.fixture(name="bpmn_zaak")
def fixture_bpmn_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    zac_group: str,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> JsonObject:
    """A zaak of the BPMN test zaaktype started in ZAC; cleanup deletes it and its documents from Open Zaak."""
    need_bootstrap("zac-bpmn-process")
    zaaktype = bpmn_zaaktype(openzaak)
    parameters = {"zaaktype": {"uuid": uuid_of(zaaktype["url"]), "omschrijving": zaaktype["omschrijving"]}}
    zaak = create_zaak(
        zac, urls["zac"], {**parameters, "defaultGroepId": zac_group}, omschrijving=registry.tagged("bpmn")
    )
    url = f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}"
    registry.add(f"zaak {zaak['identificatie']}", lambda: delete_zaak(openzaak, url, with_documents=True))
    return zaak


def intake(zac: requests.Session, zac_url: str, zaak: JsonObject, group: str) -> None:
    """Complete the intake: assign the zaak to the group and the test admin, and choose its end status and resultaat."""
    data = {
        "AM_TeamBehandelaar_Groep": group,
        "AM_TeamBehandelaar_Medewerker": ADMIN.username,
        "ZK_Status": EINDSTATUS,
        "ZK_Result": EINDSTATUS,
    }
    complete_task(zac, zac_url, open_task(zac, zac_url, str(zaak["uuid"]), INTAKE), data)


def signed_document(zac: requests.Session, zac_url: str, zaak: JsonObject, registry: ResourceRegistry) -> str:
    """Upload a PDF to the zaak, then select and sign it in the process's two document tasks; its uuid."""
    uuid = str(zaak["uuid"])
    types = get_entries(zac, f"{zac_url}/rest/informatieobjecten/informatieobjecttypes/zaak/{uuid}")
    name = f"{registry.tagged('bpmn-document')}.pdf"
    form = {
        "titel": name,
        "bestandsnaam": name,
        "formaat": "application/pdf",
        "informatieobjectTypeUUID": str(types[0]["uuid"]),
        "vertrouwelijkheidaanduiding": "OPENBAAR",
        "status": "definitief",
        "taal": "dut",
        "creatiedatum": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M+00:00"),
        "auteur": "podiumd-tests",
    }
    upload = zac.post(
        f"{zac_url}/rest/informatieobjecten/informatieobject/{uuid}/{registry.tagged('upload')}",
        params={"taakObject": "false"},
        data=form,
        files={"file": (name, b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    document = str(expect_status(upload, HTTPStatus.OK).json()["uuid"])
    row = [{"selected": True, "titel": name, "uuid": document}]
    complete_task(zac, zac_url, open_task(zac, zac_url, uuid, SELECT), {"ZAAK_Documenten_Ondertekenen_Selectie": row})
    complete_task(zac, zac_url, open_task(zac, zac_url, uuid, SIGN), {"ZAAK_Documenten_Te_Ondertekenen": row})
    return document


@pytest.mark.source(
    "podiumd-tests",
    "The BPMN tests must not depend on the estate's PABC dataset: bootstrap maps its own role in its own domain.",
)
@pytest.mark.scenario("""
    Given podiumd-tests' own realm role, which bootstrap gives the test admin
    When ZAC asks PABC for the rights of that role alone
    Then PABC gives the roles behandelaar and coordinator on the BPMN test zaaktype
    And on no zaaktype of the estate
""")
def test_bpmn_rights_come_from_podiumd_tests_own_pabc_role(
    http: requests.Session, urls: dict[str, str], pabc_api_key: str, need_bootstrap: Callable[..., None]
) -> None:
    """PABC's decision for role ptest-bootstrap-zac alone covers the BPMN test zaaktype and nothing else."""
    need_bootstrap("zac-bpmn-process")
    decision = expect_status(decide(http, urls["pabc"], pabc_api_key, [ZAC_FUNCTIONAL_ROLE]), HTTPStatus.OK).json()
    assert mapped_application_roles(decision, BPMN_ZAAKTYPE) == set(ZAC_APPLICATION_ROLES)
    covered = {str(section(r, "entityType").get("id")) for r in entries(decision.get("results")) if r.get("entityType")}
    assert covered == {BPMN_ZAAKTYPE}


@pytest.mark.source(FEATURE, "Bob creates a BPMN zaak; it is in the werkvoorraad.")
@pytest.mark.source(FEATURE, "Bob opens the initial task form of the BPMN process.")
@pytest.mark.scenario("""
    Given a zaaktype that ZAC handles with a BPMN process
    When the behandelaar starts a zaak of that zaaktype in ZAC
    Then the zaak is in the werkvoorraad
    And its first task is the intake, with the intake form, for the zaak's group and not yet assigned to anyone
""")
def test_bpmn_zaak_starts_with_its_intake_form(
    zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject, zac_group: str
) -> None:
    """A new zaak of the BPMN zaaktype starts the process: the intake task opens with its form.io form."""
    wait_in_werkvoorraad(zac, urls["zac"], str(bpmn_zaak["identificatie"]))
    task = open_task(zac, urls["zac"], str(bpmn_zaak["uuid"]), INTAKE)
    assert section(task, "formioFormulier").get("name") == "ptestIntakeForm"
    # The task goes to the zaak's behandelaar, and a new zaak has none yet.
    assert (section(task, "groep").get("id"), section(task, "behandelaar").get("id")) == (zac_group, None)


@pytest.mark.source(FEATURE, "Bob changes the assigned user and group, fills in and submits the task form.")
@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC with its intake task open
    When the behandelaar submits the intake with a group and a behandelaar
    Then the zaak is assigned to that group and behandelaar
    And the next task, selecting documents to sign, is for that group and behandelaar
""")
def test_intake_assigns_the_zaak_and_its_next_task(
    zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject, zac_group: str
) -> None:
    """The intake form's group and behandelaar go to the zaak (UpdateZaakAssignmentDelegate) and the next task."""
    intake(zac, urls["zac"], bpmn_zaak, zac_group)
    zaak = read_zaak(zac, urls["zac"], str(bpmn_zaak["uuid"]))
    assert (section(zaak, "groep").get("id"), section(zaak, "behandelaar").get("id")) == (zac_group, ADMIN.username)
    task = open_task(zac, urls["zac"], str(bpmn_zaak["uuid"]), SELECT)
    assert (section(task, "groep").get("id"), section(task, "behandelaar").get("id")) == (zac_group, ADMIN.username)


@pytest.mark.source(FEATURE, "Bob verifies the documents to sign and confirms signing.")
@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC past its intake, with a PDF document
    When the behandelaar selects the document in the select task
    And confirms it in the sign task
    Then the document has the indication ondertekend
""")
def test_selected_document_is_signed(
    zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject, zac_group: str, registry: ResourceRegistry
) -> None:
    """The process signs the documents chosen in its two document tasks (SignDocumentDelegate)."""
    intake(zac, urls["zac"], bpmn_zaak, zac_group)
    document = signed_document(zac, urls["zac"], bpmn_zaak, registry)
    found = expect_status(zac.get(f"{urls['zac']}/rest/informatieobjecten/informatieobject/{document}"), HTTPStatus.OK)
    assert "ONDERTEKEND" in strings(found.json().get("indicaties"))


@pytest.mark.source(FEATURE, "Bob inspects and confirms the summary form; the zaak ends with its resultaat.")
@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC whose intake chose the end status and resultaat
    And whose documents are signed
    When the behandelaar confirms the summary
    Then the zaak is closed with the end status
    And it has the chosen resultaat
""")
def test_summary_closes_the_zaak_with_its_resultaat(
    zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject, zac_group: str, registry: ResourceRegistry
) -> None:
    """After the summary, the process sets the intake's status and resultaat (UpdateZaakJavaDelegate): closed."""
    intake(zac, urls["zac"], bpmn_zaak, zac_group)
    signed_document(zac, urls["zac"], bpmn_zaak, registry)
    complete_task(zac, urls["zac"], open_task(zac, urls["zac"], str(bpmn_zaak["uuid"]), SUMMARY), {})
    zaak = read_zaak(zac, urls["zac"], str(bpmn_zaak["uuid"]))
    assert not zaak["isOpen"], zaak.get("status")
    assert section(zaak, "status").get("naam") == EINDSTATUS
    assert section(section(zaak, "resultaat"), "resultaattype").get("naam") == EINDSTATUS, zaak.get("resultaat")
