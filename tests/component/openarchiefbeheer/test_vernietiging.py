"""Open Archiefbeheer: the destruction of a vernietigingslijst of the test's own zaak, also one ZAC closed, and
the short procedure.

Ported from TA regression 170 and 171. The destruction and the short procedure change OAB's global ArchiveConfig, so
these tests are destructive (tier chaos) and run on one worker.
"""

from __future__ import annotations

import io
import zipfile

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.bootstrap.bpmn import SELECT
from podiumd_tests.bootstrap.bpmn import SIGN
from podiumd_tests.bootstrap.bpmn import SUMMARY
from podiumd_tests.bootstrap.bpmn import complete_intake
from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.names import PRODUCTAANVRAAG_OBJECTTYPE
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.bootstrap.names import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.mailpit import received
from podiumd_tests.oab import cache_zaken
from podiumd_tests.oab import list_status
from podiumd_tests.oab import new_list
from podiumd_tests.oab import queue
from podiumd_tests.oab import ready_to_delete
from podiumd_tests.oab import review
from podiumd_tests.oab import run_destruction
from podiumd_tests.oab import set_config
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openzaak import DOCUMENTEN
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.zac import heropenen
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_taken import complete_task
from podiumd_tests.zac_taken import open_task

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.cluster,
    pytest.mark.requires("openarchiefbeheer", "openzaak", "cluster"),
]

REG_170 = pytest.mark.source(
    "TA regression/170-oab-destruction-execute.spec.ts",
    "OAB's record manager starts the destruction, after which a report is made.",
)
REG_171 = pytest.mark.source(
    "TA regression/171-oab-short-procedure.spec.ts",
    "OAB's short procedure: the full process with the archivist skipped.",
)


@pytest.mark.tc("ABC-024")
@REG_170
@pytest.mark.scenario("""
    Given a vernietigingslijst that the reviewer and the archivist accepted
    When the record manager starts the destruction
    Then the destruction is planned after today
    When the record manager aborts the destruction
    Then the list is new again
""")
def test_destruction_waits_and_can_be_aborted(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """Started destruction is planned after the waiting period, and aborting returns the list (TA reg-170 ABC-034)."""
    lijst = ready_to_delete(oab, api, zaak, registry)
    planned = queue(oab, api, lijst).get("plannedDestructionDate")
    assert planned
    assert str(planned) > today()
    abort = {"comment": "podiumd-tests"}
    expect_status(oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/abort/", json=abort), HTTPStatus.OK)
    assert list_status(oab, api, lijst) == "new"


@pytest.fixture(name="oab_config")
def fixture_oab_config(podiumd_env: Environment) -> Iterator[Callable[..., None]]:
    """set(model, **fields): change OAB's global ArchiveConfig or EmailConfig for this test; the old values come back."""
    old: dict[str, dict[str, object]] = {}

    def change(model: str, **fields: object) -> None:
        for field, value in set_config(podiumd_env, model, fields).items():
            old.setdefault(model, {}).setdefault(field, value)

    yield change
    for model, fields in old.items():
        set_config(podiumd_env, model, fields)


# The destruction never completes on Open Zaak 1.29.3.
DESTRUCTION_FAILS = pytest.mark.xfail(
    strict=True,
    reason="[open-archiefbeheer-4] Open Zaak 1.29.3 answers 500 on DELETE of a zaak with a resultaat although it deletes it"
    " (test_closed_zaak_delete_answers_204); Open Archiefbeheer marks the item failed, so the list"
    " never reaches deleted and files no report; open-zaak#2484",
)
# Columns of the report's sheet "Deleted zaken": the metadata OAB keeps of a destroyed zaak.
REPORT_COLUMNS = ("Zaak Identificatie", "Zaaktype Identificatie", "Resultaat", "Zaak Startdatum", "Zaak Einddatum")


def destroy(
    podiumd_env: Environment,
    oab: Callable[[str], requests.Session],
    api: str,
    openzaak: ApiClient,
    parts: ZaaktypeParts,
    registry: ResourceRegistry,
    lijst: str,
) -> str:
    """Destroy the list now; once it is deleted, the text of the report the record manager downloads.

    The report goes to a zaak of the test zaaktype (ArchiveConfig, set back after the test).
    """
    naam = str(
        expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()["name"]
    )

    def delete_report() -> None:
        for rapport in openzaak.list(f"{ZAKEN}/zaken", {"zaaktype": parts.zaaktype}):
            if naam in str(rapport.get("toelichting") or ""):
                delete_zaak(openzaak, str(rapport["url"]), with_documents=True)

    registry.add(f"destruction report of {naam}", delete_report)
    assert run_destruction(podiumd_env, oab, api, lijst) == "succeeded"
    assert list_status(oab, api, lijst) == "deleted"
    report = oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/download_report/")
    # An xlsx: its cell texts are in the shared strings.
    with zipfile.ZipFile(io.BytesIO(expect_status(report, HTTPStatus.OK).content)) as workbook:
        return workbook.read("xl/sharedStrings.xml").decode()


def report_config(parts: ZaaktypeParts) -> dict[str, object]:
    """ArchiveConfig fields that file the destruction report as a zaak of the test zaaktype."""
    return {
        "bronorganisatie": TEST_CATALOGUS_RSIN,
        "zaaktype": parts.zaaktype,
        "statustype": str(parts.statustypen[-1]["url"]),
        "resultaattype": parts.resultaattypen[0],
        "informatieobjecttype": parts.informatieobjecttype,
    }


@pytest.mark.destructive
@DESTRUCTION_FAILS
@pytest.mark.tc("ABC-032", "ABC-033")
@REG_170
@pytest.mark.scenario("""
    Given a vernietigingslijst of one closed zaak that the reviewer and the archivist accepted
    When the record manager starts the destruction and it runs
    Then the destruction succeeds
    And the list is deleted
    And the zaak is gone from Open Zaak
    And the destruction report names the zaak with its metadata columns
""")
def test_destruction_deletes_the_zaak_and_leaves_a_report(
    podiumd_env: Environment,
    oab: Callable[[str], requests.Session],
    api: str,
    openzaak: ApiClient,
    zaak: JsonObject,
    parts: ZaaktypeParts,
    registry: ResourceRegistry,
    oab_config: Callable[..., None],
) -> None:
    """The destruction deletes the zaak in Open Zaak; the report keeps its metadata (TA reg-170)."""
    oab_config("ArchiveConfig", **report_config(parts))
    report = destroy(podiumd_env, oab, api, openzaak, parts, registry, ready_to_delete(oab, api, zaak, registry))
    openzaak.request("GET", str(zaak["url"]), HTTPStatus.NOT_FOUND)
    assert str(zaak["identificatie"]) in report
    assert [c for c in REPORT_COLUMNS if c not in report] == []


@pytest.mark.destructive
@pytest.mark.requires("objecten")
@pytest.mark.source(
    "podiumd-tests",
    "Destroying a zaak also deletes its productaanvraag in Objecten, which needs OAB's token to write that objecttype.",
)
@pytest.mark.scenario("""
    Given a closed zaak linked to a productaanvraag in Objecten
    And a vernietigingslijst of the zaak that the reviewer and the archivist accepted
    When the destruction runs
    Then the productaanvraag is gone from Objecten
""")
def test_destruction_deletes_the_productaanvraag_of_the_zaak(
    podiumd_env: Environment,
    oab: Callable[[str], requests.Session],
    api: str,
    openzaak: ApiClient,
    objecten: ApiClient,
    zaak: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """OAB deletes the productaanvraag object linked to the zaak before it deletes the zaak itself."""
    kenmerk = registry.tagged("oab-productaanvraag")
    aanvraag = make_productaanvraag(
        objecten, registry, objecttype_url(podiumd_env, PRODUCTAANVRAAG_OBJECTTYPE), kenmerk, kenmerk
    )
    link = {
        "zaak": zaak["url"],
        "object": aanvraag["url"],
        "objectType": "overige",
        "objectTypeOverige": "productaanvraag",
    }
    zaakobject = openzaak.post(f"{ZAKEN}/zaakobjecten", link)
    registry.add("zaakobject", lambda: openzaak.delete(str(zaakobject["url"])))
    # The list itself may fail on the zaak (open-archiefbeheer-4); the objects go first.
    run_destruction(podiumd_env, oab, api, ready_to_delete(oab, api, zaak, registry))
    objecten.request("GET", str(aanvraag["url"]), HTTPStatus.NOT_FOUND)


@pytest.mark.destructive
@pytest.mark.tc("ABC-038")
@REG_171
@pytest.mark.scenario("""
    Given the test zaaktype takes the short procedure
    And a vernietigingslijst of a closed zaak of that zaaktype, ready for review
    When the reviewer accepts the list
    Then the list is ready to delete
""")
def test_short_procedure_skips_the_archivist(
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    oab_config: Callable[..., None],
) -> None:
    """For a zaaktype with the short procedure, the reviewer's acceptance makes the list ready to delete (TA reg-171)."""
    oab_config("ArchiveConfig", zaaktypes_short_process=[TEST_ZAAKTYPE])
    lijst = new_list(oab, api, zaak, registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    assert list_status(oab, api, lijst) == "ready_to_delete"


@pytest.mark.destructive
@pytest.mark.tc("ABC-034", "ABC-035")
@pytest.mark.source(
    "draaiboek ABC-034", "A functioneel beheerder chooses in OAB's settings which zaaktypen take the short procedure."
)
@pytest.mark.scenario("""
    When the record manager sets which zaaktypen take the short procedure
    Then Open Archiefbeheer refuses the change
    When the functioneel beheerder sets the test zaaktype to take the short procedure
    Then the record manager sees that setting
""")
def test_beheerder_sets_the_short_procedure_zaaktypen(
    oab: Callable[[str], requests.Session], api: str, registry: ResourceRegistry
) -> None:
    """Only the functioneel beheerder changes which zaaktypen take the short procedure, and the choice is kept."""
    config = f"{api}/archive-config"
    old = expect_status(oab("beheerder").get(config), HTTPStatus.OK).json()["zaaktypesShortProcess"]
    registry.add(
        "short procedure zaaktypen",
        lambda: expect_status(oab("beheerder").patch(config, json={"zaaktypesShortProcess": old}), HTTPStatus.OK),
    )
    refused = oab("recordmanager").patch(config, json={"zaaktypesShortProcess": [TEST_ZAAKTYPE]})
    expect_status(refused, *REFUSED)
    expect_status(oab("beheerder").patch(config, json={"zaaktypesShortProcess": [TEST_ZAAKTYPE]}), HTTPStatus.OK)
    assert expect_status(oab("recordmanager").get(config), HTTPStatus.OK).json()["zaaktypesShortProcess"] == [
        TEST_ZAAKTYPE
    ]


@pytest.mark.destructive
@pytest.mark.tc("ABC-036")
@pytest.mark.source(
    "draaiboek ABC-036",
    "Zaaktypen with the short procedure can only follow it; the route through the archivist is closed.",
)
@pytest.mark.scenario("""
    Given the test zaaktype takes the short procedure
    And the reviewer accepted a vernietigingslijst of a closed zaak of that zaaktype
    When the archivist reviews the list
    Then Open Archiefbeheer refuses the review
    And the list stays ready to delete
""")
def test_short_procedure_list_cannot_go_to_the_archivist(
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    oab_config: Callable[..., None],
) -> None:
    """For a zaaktype with the short procedure, the archivist cannot review the accepted list."""
    oab_config("ArchiveConfig", zaaktypes_short_process=[TEST_ZAAKTYPE])
    lijst = new_list(oab, api, zaak, registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    body = {"destructionList": lijst, "listFeedback": "podiumd-tests", "decision": "accepted"}
    response = oab("archivist").post(f"{api}/destruction-list-reviews/", json=body)
    expect_status(response, HTTPStatus.FORBIDDEN, HTTPStatus.BAD_REQUEST)
    assert list_status(oab, api, lijst) == "ready_to_delete"


@pytest.mark.destructive
@DESTRUCTION_FAILS
@pytest.mark.tc("ABC-039", "ABC-040", "ABC-041")
@pytest.mark.source(
    "draaiboek ABC-039",
    "After a short-procedure destruction a report is made that can be exported for the destruction statement.",
)
@pytest.mark.scenario("""
    Given the test zaaktype takes the short procedure
    And the reviewer accepted a vernietigingslijst of a closed zaak of that zaaktype
    When the destruction runs
    Then the destruction succeeds
    And the list is deleted
    And the destruction report names the zaak with its metadata columns
""")
def test_short_procedure_destruction_leaves_a_report(
    podiumd_env: Environment,
    oab: Callable[[str], requests.Session],
    api: str,
    openzaak: ApiClient,
    zaak: JsonObject,
    parts: ZaaktypeParts,
    registry: ResourceRegistry,
    oab_config: Callable[..., None],
) -> None:
    """After a short-procedure destruction the report lists the zaak with its metadata columns."""
    oab_config("ArchiveConfig", zaaktypes_short_process=[TEST_ZAAKTYPE], **report_config(parts))
    lijst = new_list(oab, api, zaak, registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    report = destroy(podiumd_env, oab, api, openzaak, parts, registry, lijst)
    assert str(zaak["identificatie"]) in report
    assert [c for c in REPORT_COLUMNS if c not in report] == []


ZAC_TEAM = pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, integraties-intake):"
    " a zaak handled in ZAC is destroyed with its documents through a vernietigingslijst, which mails its users; a"
    " reopened zaak is not.",
)
# A zaak of the BPMN test zaaktype through ZAC.
ZAC_ZAAK = pytest.mark.requires("zac", "pabc", "keycloak")


@pytest.fixture(name="zac_zaak_on_list")
def fixture_zac_zaak_on_list(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    openzaak: ApiClient,
    oab: Callable[[str], requests.Session],
    api: str,
    registry: ResourceRegistry,
) -> tuple[JsonObject, str, str]:
    """A BPMN zaak with a PDF, closed by its process in ZAC, due for destruction and on an accepted list.

    Returns the zaak in Open Zaak, its document's URL there and the list's uuid.
    """
    zac_url, uuid = urls["zac"], str(bpmn_zaak["uuid"])
    document = uploaded_document(zac, zac_url, bpmn_zaak, registry, suffix="pdf")
    complete_intake(zac, zac_url, bpmn_zaak, (zac_group, ADMIN.username))
    for task, field in ((SELECT, "ZAAK_Documenten_Ondertekenen_Selectie"), (SIGN, "ZAAK_Documenten_Te_Ondertekenen")):
        complete_task(zac, zac_url, open_task(zac, zac_url, uuid, task), {field: []})
    complete_task(zac, zac_url, open_task(zac, zac_url, uuid, SUMMARY), {})
    url = openzaak.url(f"{ZAKEN}/zaken/{uuid}")
    yesterday = (date.today() - timedelta(days=1)).isoformat()  # noqa: DTZ011  # Open Zaak's local date
    zaak = openzaak.request("PATCH", url, HTTPStatus.OK, json={"archiefactiedatum": yesterday}).json()
    if zaak.get("archiefnominatie") != "vernietigen":
        pytest.skip(
            f"zaak {zaak.get('identificatie')} has archiefnominatie {zaak.get('archiefnominatie')!r}, not vernietigen"
        )
    registry.add(f"OAB cache of {url}", lambda: cache_zaken(podiumd_env, [url], cached=False))
    cache_zaken(podiumd_env, [url], cached=True)
    lijst = ready_to_delete(oab, api, zaak, registry)
    return zaak, openzaak.url(f"{DOCUMENTEN}/enkelvoudiginformatieobjecten/{document['uuid']}"), lijst


def _is_in_open_zaak(openzaak: ApiClient, url: str) -> bool:
    return openzaak.request("GET", url, HTTPStatus.OK, HTTPStatus.NOT_FOUND).status_code == HTTPStatus.OK


@pytest.mark.xfail(
    strict=True,
    reason="[open-archiefbeheer-8] Open Archiefbeheer 2.0.0 keeps the documents of a destroyed zaak (resource_type "
    "enkelvoudiginformatieobject vs enkelvoudiginformatieobjecten); fixed on main (open-archiefbeheer#1124), not released",
)
@pytest.mark.destructive
@ZAC_ZAAK
@ZAC_TEAM
@pytest.mark.scenario("""
    Given a zaak with a document that ZAC closed, due for destruction
    And a vernietigingslijst of the zaak that the reviewer and the archivist accepted
    When the destruction runs
    Then the document is gone from Open Zaak
    And the zaak is gone from Open Zaak
""")
def test_destruction_deletes_a_zac_zaak_and_its_document(
    podiumd_env: Environment,
    oab: Callable[[str], requests.Session],
    api: str,
    openzaak: ApiClient,
    zac_zaak_on_list: tuple[JsonObject, str, str],
) -> None:
    """OAB deletes the documents of the zaak, then the zaak."""
    zaak, document, lijst = zac_zaak_on_list
    run_destruction(podiumd_env, oab, api, lijst)
    assert (_is_in_open_zaak(openzaak, document), _is_in_open_zaak(openzaak, str(zaak["url"]))) == (False, False)


@pytest.mark.xfail(
    strict=True,
    reason="[open-archiefbeheer-9] Open Archiefbeheer 2.0.0 destroys a zaak reopened after its list was accepted: it "
    "checks only its cached archiefactiedatum; not yet reported upstream",
)
@pytest.mark.destructive
@ZAC_ZAAK
@ZAC_TEAM
@pytest.mark.scenario("""
    Given a zaak with a document that ZAC closed, due for destruction
    And a vernietigingslijst of the zaak that the reviewer and the archivist accepted
    When the behandelaar reopens the zaak in ZAC
    And the destruction runs
    Then the zaak and its document are still in Open Zaak
""")
def test_zaak_reopened_in_zac_is_not_destroyed(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    oab: Callable[[str], requests.Session],
    api: str,
    openzaak: ApiClient,
    zac_zaak_on_list: tuple[JsonObject, str, str],
) -> None:
    """Reopening clears the zaak's archiefnominatie and archiefactiedatum in Open Zaak, so the zaak is not due."""
    zaak, document, lijst = zac_zaak_on_list
    expect_status(heropenen(zac, urls["zac"], bpmn_zaak), HTTPStatus.OK)
    run_destruction(podiumd_env, oab, api, lijst)
    assert (_is_in_open_zaak(openzaak, document), _is_in_open_zaak(openzaak, str(zaak["url"]))) == (True, True)


# OAB's mails per event: (EmailConfig field prefix, the user who gets it).
MAILS = (("review_required", "reviewer"), ("changes_requested", "recordmanager"))
MAIL_TIMEOUT = 60


@pytest.mark.destructive
@pytest.mark.requires("mailpit")
@ZAC_TEAM
@pytest.mark.scenario("""
    Given Open Archiefbeheer has mails for a list to review and for changes requested
    When the record manager makes a vernietigingslijst ready to review
    Then the reviewer gets the mail naming the list
    When the reviewer rejects the list
    Then the record manager gets the mail naming the list
""")
def test_reviewer_and_record_manager_get_their_mails(  # OAB, its config and Mailpit
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    oab_config: Callable[..., None],
    mailpit: ApiClient,
) -> None:
    """OAB mails the reviewer when a list is ready to review, and its author when the reviewer requests changes."""
    subjects = {event: registry.tagged(f"oab-{event}") for event, _ in MAILS}
    fields = {
        f"{part}_{event}{suffix}": value
        for event, subject in subjects.items()
        for part, suffix, value in (
            ("subject", "", subject),
            ("body", "_text", "{{ list_name }}"),
            ("body", "_html", "<p>{{ list_name }}</p>"),
        )
    }
    oab_config("EmailConfig", **fields)
    lijst = new_list(oab, api, zaak, registry)
    naam = str(
        expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()["name"]
    )
    proposals = [{"zaakUrl": zaak["url"], "feedback": "bewaren"}]
    for event, role in MAILS:
        if event == "changes_requested":
            review(oab, api, "reviewer", lijst, decision="rejected", zakenReviews=proposals)
        to = user_email(f"{PREFIX}-{role}")
        assert naam in received(mailpit, registry, timeout=MAIL_TIMEOUT, to=to, subject=subjects[event])
