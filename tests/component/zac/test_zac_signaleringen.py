"""ZAC's signaleringen on the dashboard and by mail to the test admin, for a BPMN zaak a behandelaar assigns to the admin.

ZAC mails a signalering to the user's e-mail address in Keycloak, which bootstrap sets to @example.invalid.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.bootstrap.bpmn import INTAKE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.mailpit import quoted
from podiumd_tests.mailpit import received_mails
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import open_task
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import toekennen_taak
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_signaleringen import signalering_taken
from podiumd_tests.zac_signaleringen import signalering_zaken

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    # ZAC signals a zaak on its name and a new document from Open Notificaties' notifications.
    pytest.mark.requires("zac", "openzaak", "keycloak", "opennotificaties"),
    # The tests change the test admin's settings; one at a time.
    pytest.mark.xdist_group("zac-signaleringen"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md,"
        " zoeken-werklijsten-dashboard): signaleringen.",
    ),
]

ZAAK_OP_NAAM, DOCUMENT = "ZAAK_OP_NAAM", "ZAAK_DOCUMENT_TOEGEVOEGD"
MAIL_TIMEOUT = 60


@pytest.fixture(name="behandelaar")
def fixture_behandelaar(zac_as: Callable[[str], requests.Session]) -> requests.Session:
    """The behandelaar who acts on the admin's zaak; ZAC does not signal a user's own actions on taken."""
    return zac_as("behandelaar")


def _on_dashboard(zac: requests.Session, zac_url: str, soort: str, zaak: JsonObject) -> None:
    wait_until(
        lambda: zaak["identificatie"] in signalering_zaken(zac, zac_url, soort),
        timeout=INDEX_TIMEOUT,
        description=f"zaak {zaak['identificatie']} on the dashboard list {soort}",
    )


def _assign_to_admin(behandelaar: requests.Session, zac_url: str, zaak: JsonObject, groep: str) -> None:
    expect_status(toekennen(behandelaar, zac_url, zaak, groep, ADMIN.username), HTTPStatus.OK)


@pytest.mark.scenario("""
    Given the test admin wants dashboard signals for zaken put on their name and documents added to their zaken
    When a behandelaar assigns a zaak to the admin
    Then the admin's dashboard lists the zaak among the zaken on their name
    When the behandelaar adds a document to the zaak
    Then the admin's dashboard lists the zaak among the zaken with a new document
    When the admin opens the zaak
    Then neither list holds the zaak any more
""")
def test_zaak_on_my_name_and_new_document_show_on_the_dashboard_until_opened(
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    behandelaar: requests.Session,
    signaleringen: Callable[..., None],
    registry: ResourceRegistry,
) -> None:
    """ZAAK_OP_NAAM and ZAAK_DOCUMENT_TOEGEVOEGD signal the admin; reading the zaak deletes both."""
    signaleringen(ZAAK_OP_NAAM=True, ZAAK_DOCUMENT_TOEGEVOEGD=True)
    _assign_to_admin(behandelaar, urls["zac"], bpmn_zaak, zac_group)
    _on_dashboard(zac, urls["zac"], ZAAK_OP_NAAM, bpmn_zaak)
    uploaded_document(behandelaar, urls["zac"], bpmn_zaak, registry, suffix="pdf")
    _on_dashboard(zac, urls["zac"], DOCUMENT, bpmn_zaak)
    read_zaak(zac, urls["zac"], str(bpmn_zaak["uuid"]))
    for soort in (ZAAK_OP_NAAM, DOCUMENT):
        assert bpmn_zaak["identificatie"] not in signalering_zaken(zac, urls["zac"], soort), soort


@pytest.mark.scenario("""
    Given the test admin wants dashboard signals for zaken put on their name
    When a behandelaar starts a zaak with the admin as its behandelaar
    Then the admin's dashboard lists the zaak among the zaken on their name
""")
def test_zaak_started_on_my_name_shows_on_the_dashboard(
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_parameters: JsonObject,
    openzaak: ApiClient,
    behandelaar: requests.Session,
    signaleringen: Callable[..., None],
    registry: ResourceRegistry,
) -> None:
    """ZAAK_OP_NAAM signals the behandelaar another user assigns a new zaak to when creating it."""
    signaleringen(ZAAK_OP_NAAM=True)
    omschrijving = registry.tagged("bpmn")
    zaak = create_zaak(
        behandelaar, urls["zac"], bpmn_parameters, omschrijving=omschrijving, behandelaar={"id": ADMIN.username}
    )
    clean_up_zaak(zac, urls["zac"], openzaak, registry, zaak)
    _on_dashboard(zac, urls["zac"], ZAAK_OP_NAAM, zaak)


@pytest.mark.scenario("""
    Given the test admin wants no dashboard signal for zaken put on their name, but one for documents added
    When a behandelaar assigns a zaak to the admin and adds a document to it
    Then the admin's dashboard lists the zaak among the zaken with a new document
    And not among the zaken on their name
""")
def test_signalering_setting_off_gives_no_dashboard_signal(
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    behandelaar: requests.Session,
    signaleringen: Callable[..., None],
    registry: ResourceRegistry,
) -> None:
    """With ZAAK_OP_NAAM off no signal comes; the later document signal shows ZAC handled both notifications."""
    signaleringen(ZAAK_OP_NAAM=False, ZAAK_DOCUMENT_TOEGEVOEGD=True)
    _assign_to_admin(behandelaar, urls["zac"], bpmn_zaak, zac_group)
    uploaded_document(behandelaar, urls["zac"], bpmn_zaak, registry, suffix="pdf")
    _on_dashboard(zac, urls["zac"], DOCUMENT, bpmn_zaak)
    assert bpmn_zaak["identificatie"] not in signalering_zaken(zac, urls["zac"], ZAAK_OP_NAAM)


@pytest.mark.requires("mailpit")
@pytest.mark.scenario("""
    Given the test admin wants a mail, and no dashboard signal, for zaken put on their name
    When a behandelaar assigns a zaak to the admin
    Then the admin gets a mail with the zaak's omschrijving and zaaknummer
    And the admin's dashboard does not list the zaak among the zaken on their name
""")
def test_zaak_on_my_name_gives_a_signalering_mail(
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    behandelaar: requests.Session,
    signaleringen: Callable[..., None],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """ZAAK_OP_NAAM with mail on mails the admin's Keycloak address; ZAC stores the dashboard signal before it mails."""
    signaleringen(mail=True, ZAAK_OP_NAAM=False)
    _assign_to_admin(behandelaar, urls["zac"], bpmn_zaak, zac_group)
    query = f"to:{quoted(user_email(ADMIN.username))} {quoted(str(bpmn_zaak['identificatie']))}"
    mail = received_mails(mailpit, registry, query, timeout=MAIL_TIMEOUT)[0]
    assert str(bpmn_zaak["omschrijving"]) in str(mail.get("Subject")), mail.get("Subject")
    assert bpmn_zaak["identificatie"] not in signalering_zaken(zac, urls["zac"], ZAAK_OP_NAAM)


@pytest.mark.scenario("""
    Given the test admin wants dashboard signals for taken put on their name
    When a behandelaar assigns the intake taak of a zaak to the admin
    Then the admin's dashboard lists the taak
    When the admin opens the taak
    Then the dashboard no longer lists it
""")
def test_taak_on_my_name_shows_on_the_dashboard_until_opened(
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    behandelaar: requests.Session,
    signaleringen: Callable[..., None],
) -> None:
    """TAAK_OP_NAAM signals the assignee when another user assigns the taak; reading the taak deletes it."""
    signaleringen(TAAK_OP_NAAM=True)
    taak = open_task(behandelaar, urls["zac"], str(bpmn_zaak["uuid"]), INTAKE)
    toekennen_taak(behandelaar, urls["zac"], taak, zac_group, ADMIN.username)
    wait_until(
        lambda: taak["id"] in signalering_taken(zac, urls["zac"]),
        timeout=INDEX_TIMEOUT,
        description=f"taak {taak['id']} on the dashboard",
    )
    expect_status(zac.get(f"{urls['zac']}/rest/taken/{taak['id']}"), HTTPStatus.OK)
    assert taak["id"] not in signalering_taken(zac, urls["zac"])
