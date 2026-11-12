"""ZAC's signaleringen on the dashboard and by mail to the test admin, for a BPMN zaak a behandelaar assigns to the admin.

ZAC mails a signalering to the user's e-mail address in Keycloak, which bootstrap sets to @example.invalid.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.bootstrap.bpmn import INTAKE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_other_domain_group
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import is_zaak_listed
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import zac_session
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_signaleringen import save_signalering_setting
from podiumd_tests.zac_signaleringen import signalering_mail
from podiumd_tests.zac_signaleringen import signalering_overzichten
from podiumd_tests.zac_signaleringen import signalering_taken
from podiumd_tests.zac_signaleringen import signalering_zaken
from podiumd_tests.zac_taken import open_task
from podiumd_tests.zac_taken import toekennen_taak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
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
    Then the admin gets a mail with the zaak's omschrijving and zaaknummer, and a link that opens the zaak
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
    mail = signalering_mail(mailpit, registry, ADMIN.username, str(bpmn_zaak["identificatie"]), timeout=MAIL_TIMEOUT)
    assert str(bpmn_zaak["omschrijving"]) in str(mail.get("Subject")), mail.get("Subject")
    assert f'href="{urls["zac"]}/zaken/{bpmn_zaak["identificatie"]}"' in str(mail.get("HTML"))
    assert bpmn_zaak["identificatie"] not in signalering_zaken(zac, urls["zac"], ZAAK_OP_NAAM)


@pytest.mark.requires("mailpit")
@pytest.mark.scenario("""
    Given the test admin wants a mail, and no dashboard signal, for taken put on their name
    When a behandelaar assigns the intake taak of a zaak to the admin
    Then the admin gets a mail with the zaaknummer and a link that opens the taak
""")
def test_taak_on_my_name_gives_a_signalering_mail(
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    behandelaar: requests.Session,
    signaleringen: Callable[..., None],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """TAAK_OP_NAAM with mail on mails the admin's Keycloak address the taak's link, its TAAK_LINK."""
    signaleringen(mail=True, TAAK_OP_NAAM=False)
    taak = open_task(behandelaar, urls["zac"], str(bpmn_zaak["uuid"]), INTAKE)
    toekennen_taak(behandelaar, urls["zac"], taak, zac_group, ADMIN.username)
    mail = signalering_mail(mailpit, registry, ADMIN.username, f"/taken/{taak['id']}", timeout=MAIL_TIMEOUT)
    assert f'href="{urls["zac"]}/taken/{taak["id"]}"' in str(mail.get("HTML"))


@pytest.mark.requires("mailpit")
@pytest.mark.scenario("""
    Given the test admin wants a mail, and no dashboard signal, for documents added to their zaken
    And a zaak on the admin's name
    When a behandelaar adds a document to the zaak
    Then the admin gets a mail with the zaaknummer and a link that opens the document
""")
def test_new_document_gives_a_signalering_mail(
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    behandelaar: requests.Session,
    signaleringen: Callable[..., None],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """ZAAK_DOCUMENT_TOEGEVOEGD with mail on mails the behandelaar of the zaak the document's DOCUMENT_LINK."""
    signaleringen(ZAAK_OP_NAAM=False)
    signaleringen(mail=True, ZAAK_DOCUMENT_TOEGEVOEGD=False)
    _assign_to_admin(behandelaar, urls["zac"], bpmn_zaak, zac_group)
    document = uploaded_document(behandelaar, urls["zac"], bpmn_zaak, registry, suffix="pdf")
    link = f"{urls['zac']}/informatie-objecten/{document['uuid']}"
    mail = signalering_mail(mailpit, registry, ADMIN.username, str(bpmn_zaak["identificatie"]), timeout=MAIL_TIMEOUT)
    assert f'href="{link}"' in str(mail.get("HTML"))  # noqa: B907  # an HTML attribute


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


@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given a user who is behandelaar on the BPMN test zaaktype and raadpleger on a zaaktype of another domain
    And the user wants dashboard signals for zaken put on their name
    When the test admin assigns a zaak of the BPMN test zaaktype to the user
    Then the user's dashboard lists the zaak among Mijn zaken and among the zaken on their name
    When the user loses the role on the BPMN test zaaktype and logs in again
    Then Mijn zaken no longer lists the zaak, and the zaken on their name show its zaaknummer without omschrijving
""")
def test_dashboard_hides_the_zaak_after_a_lost_role(
    zac: requests.Session,
    podiumd_env: Environment,
    urls: dict[str, str],
    registry: ResourceRegistry,
    bpmn_zaak: JsonObject,
) -> None:
    """The dashboard's Mijn zaken is a search; ZAAK_OP_NAAM lists the zaak but shows its details only with lezen."""
    zac_url = urls["zac"]
    group = make_role_group(podiumd_env, registry, "behandelaar")
    other = make_other_domain_group(podiumd_env, registry, "raadpleger")
    username, password = make_group_member(podiumd_env, registry, group, other)
    user = zac_session(podiumd_env, username, password)
    save_signalering_setting(user, zac_url, {"type": ZAAK_OP_NAAM, "dashboard": True, "mail": False})
    expect_status(toekennen(zac, zac_url, bpmn_zaak, group, username), HTTPStatus.OK)
    _on_dashboard(user, zac_url, ZAAK_OP_NAAM, bpmn_zaak)
    wait_until(
        lambda: is_zaak_listed(user, zac_url, bpmn_zaak, alleenMijnZaken=True),
        timeout=INDEX_TIMEOUT,
        description=f"zaak {bpmn_zaak['identificatie']} in Mijn zaken",
    )

    for_environment(podiumd_env).delete_group_named(group)
    after = zac_session(podiumd_env, username, password)
    assert not is_zaak_listed(after, zac_url, bpmn_zaak, alleenMijnZaken=True)
    shown = [
        item
        for item in signalering_overzichten(after, zac_url, ZAAK_OP_NAAM)
        if item.get("identificatie") == bpmn_zaak["identificatie"]
    ]
    assert [item.get("omschrijving") for item in shown] == [None], shown
