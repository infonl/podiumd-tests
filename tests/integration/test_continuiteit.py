"""Continuity: a stopped component answers no more, the others stay up and keep working, and it comes back.

Ported from TA regression 89, 124 and 144; the draaiboek's Continuïteit sheet. Each test scales a
component's main deployment to 0 and restores it afterwards.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests import ita as ita_calls
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.components import COMPONENTS
from podiumd_tests.kcc import kcc_login
from podiumd_tests.mailpit import forget_mails
from podiumd_tests.mailpit import mail_queue
from podiumd_tests.mailpit import received
from podiumd_tests.openformulieren import forget_submission
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.openformulieren import submit
from podiumd_tests.openinwoner import ask_anonymously
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import is_root_answering
from podiumd_tests.responses import is_server_error
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import clean_up_klantcontacten
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import make_submission_contact
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import ROOT_TIMEOUT
from podiumd_tests.workloads import component_down
from podiumd_tests.workloads import scaled
from podiumd_tests.zac import PRODUCTAANVRAAG_TIMEOUT
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import zaak_body
from podiumd_tests.zac_betrokkenen import make_person_initiator
from podiumd_tests.zac_productaanvraag import productaanvraag_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.destructive, pytest.mark.requires("cluster")]

INWONER, _, _ = IDENTITIES
# Open Inwoner's logins (W1), pages (W5) and zaken (W4).
WIRING = ("openinwoner-oidc-mock", "openinwoner-cms-pages", "openinwoner-zgw-group")
REGISTRATION_TIMEOUT = 90
# ZAC's call to a down Open Klant: on Cilium the zero-endpoint Service black-holes the connection, so ZAC
# answers 500 only after its own upstream timeout, longer than the session's default 15 s.
DOWN_COMPONENT_TIMEOUT = 60
# The subject of the contact form questions (bootstrap openinwoner-openklant).
QUESTION_SUBJECT = "Algemene vraag"
# Open Inwoner's Mijn zaken retries its fetch of the zaken before it shows the failure.
FETCH_RETRY_TIMEOUT_MS = 180_000
# Time a failed mail gets to be sent again after the outage.
RETRY_TIMEOUT = 8 * 60
STOPPED = ("openzaak", "openformulieren", "openklant", "opennotificaties", "openinwoner", "ita", "kiss", "zac", "omc")


@pytest.mark.parametrize("component", [requiring(c, c) for c in STOPPED])
@pytest.mark.tc("CONT-003", "CONT-004", "CONT-007", "CONT-012", "CONT-016", "CONT-020")
@pytest.mark.source(
    "TA regression/124-cluster-pod-recovery-multi.spec.ts",
    "Validates per component that it is reachable, fails while scaled to 0, and recovers once scaled back up.",
)
@pytest.mark.source(
    "TA regression/144-continuiteit-component-stop.spec.ts",
    "Really stops a component, checks how the other services behave, and starts it again.",
)
@pytest.mark.source(
    "TA regression/89-cluster-pod-recovery.spec.ts",
    "Validates that scaling a deployment to 0 stops its pod, scaling back up starts it, and the service is reachable again.",
)
@pytest.mark.scenario("""
    Given the other components of the environment answer
    When a component is stopped
    Then the stopped component answers no more
    And every other component still answers
    And the component answers again once it is started
""")
def test_stopped_component_harms_no_other(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment, component: str
) -> None:
    """While the component is stopped its root fails and every other root answers (TA reg-89, 124, 144)."""
    others = [
        c for c in sorted(urls) if c != component and c in COMPONENTS and is_root_answering(http, urls[c], ROOT_TIMEOUT)
    ]
    with component_down(podiumd_env, http, component):
        assert [c for c in others if not is_root_answering(http, urls[c], ROOT_TIMEOUT)] == []


@pytest.mark.requires("frankgateway", "openzaak", "openinwoner")
@pytest.mark.source(
    "podiumd-tests", "Checks that a Frank!Gateway outway outage does not cascade: the apps' roots still answer."
)
@pytest.mark.scenario("""
    Given the apps of the environment answer
    When the Frank!Gateway outway is stopped
    Then every app still answers
""")
def test_frankgateway_outage_does_not_cascade(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment
) -> None:
    """While the Frank!Gateway outway is down the apps' roots still answer: a gateway outage does not cascade.

    The outway has no public host; the suite reaches it through a port-forward that a pod replacement breaks, so
    the outway's own recovery is confirmed by the rollout (scaled), not by re-reading its URL. The apps route
    BRP/KvK/BAG through the outway, but their roots do not depend on it.
    """
    apps = [
        c
        for c in sorted(urls)
        if c in COMPONENTS and c != "frankgateway" and is_root_answering(http, urls[c], ROOT_TIMEOUT)
    ]
    with scaled(podiumd_env.kube, podiumd_env.deployment_for("frankgateway"), 0):
        assert [c for c in apps if not is_root_answering(http, urls[c], ROOT_TIMEOUT)] == []


def form_starts(podiumd_env: Environment, http: requests.Session, registry: ResourceRegistry) -> None:
    """Open Formulieren starts a submission of the test form; cleanup deletes it."""
    submission, _ = start_submission(http, podiumd_env.profile.urls["openformulieren"], TEST_FORM)
    forget_submission(podiumd_env, registry, str(submission["id"]))


@pytest.mark.requires("openzaak", "openformulieren", "openinwoner", "zac", "keycloak")
@pytest.mark.tc("CONT-025", "CONT-026", "CONT-028")
@pytest.mark.source("draaiboek CONT-025", "With Open Zaak unavailable, Open Formulieren works undisturbed.")
@pytest.mark.source(
    "draaiboek CONT-026",
    "With Open Zaak unavailable, the portal shows no zaken but a user-friendly message that the zaaksysteem is down.",
)
@pytest.mark.source("draaiboek CONT-028", "With Open Zaak unavailable, ZAC cannot start handling a new zaak.")
@pytest.mark.scenario("""
    Given an inwoner is logged in to Open Inwoner with DigiD
    When Open Zaak is stopped
    Then Open Formulieren still starts a form
    And Mijn zaken says that not all zaken could be fetched
    And ZAC refuses to start a new zaak but itself keeps answering
""")
def test_without_open_zaak_the_apps_say_so(
    page: Page,
    http: requests.Session,
    podiumd_env: Environment,
    zac: requests.Session,
    zac_parameters: JsonObject,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """Without Open Zaak: forms still start, Mijn zaken says the zaken could not be fetched, ZAC refuses a new zaak."""
    need_bootstrap("openformulieren-form", INWONER.name, *WIRING)
    portal_login(page, podiumd_env, "digid", INWONER, "/")
    with component_down(podiumd_env, http, "openzaak"):
        form_starts(podiumd_env, http, registry)
        response = page.goto(f"{podiumd_env.profile.urls['openinwoner']}/mijn-zaken/")
        assert response is not None, "Mijn zaken fails"
        assert response.status < HTTPStatus.INTERNAL_SERVER_ERROR, "Mijn zaken fails"
        # Mijn zaken loads the zaken after the page, and retries twice before it gives up.
        expect(page.get_by_text("Niet alle zaken konden worden opgehaald")).to_be_visible(
            timeout=FETCH_RETRY_TIMEOUT_MS
        )
        body = zaak_body(zac_parameters, omschrijving=registry.tagged("geen-oz"))
        refused = zac.post(f"{podiumd_env.profile.urls['zac']}/rest/zaken/zaak", json=body)
        assert refused.status_code >= HTTPStatus.BAD_REQUEST
        assert is_root_answering(zac, podiumd_env.profile.urls["zac"], ROOT_TIMEOUT), "ZAC itself fails"


@pytest.mark.parametrize("component", [requiring(c, c) for c in ("openklant", "opennotificaties")])
@pytest.mark.requires("openformulieren")
@pytest.mark.tc("CONT-031", "CONT-036")
@pytest.mark.source("draaiboek CONT-031", "With Open Klant unavailable, Open Formulieren works undisturbed.")
@pytest.mark.source("draaiboek CONT-036", "With Open Notificaties unavailable, Open Formulieren works undisturbed.")
@pytest.mark.scenario("""
    Given Open Formulieren has a test form
    When Open Klant or Open Notificaties is stopped
    Then Open Formulieren still starts the form
""")
def test_forms_start_without_open_klant_or_open_notificaties(
    http: requests.Session,
    podiumd_env: Environment,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    component: str,
) -> None:
    """Open Formulieren starts submissions while Open Klant or Open Notificaties is down."""
    need_bootstrap("openformulieren-form")
    with component_down(podiumd_env, http, component):
        form_starts(podiumd_env, http, registry)


@pytest.mark.requires("objecten", "openinwoner", "kiss", "zac", "keycloak")
@pytest.mark.tc("CONT-042", "CONT-043", "CONT-044")
@pytest.mark.source(
    "draaiboek CONT-042",
    "With Objecten unavailable, a field that searches Objecten fails but the portal keeps working.",
)
@pytest.mark.source(
    "draaiboek CONT-043",
    "With Objecten unavailable, a field that searches Objecten fails but the Contact (KISS) keeps working.",
)
@pytest.mark.source(
    "draaiboek CONT-044",
    "With Objecten unavailable, a field that searches Objecten fails but the zaak handling (ZAC) keeps working.",
)
@pytest.mark.scenario("""
    Given Objecten is stopped
    When an inwoner logs in to Mijn zaken with DigiD
    Then Mijn zaken opens
    And KISS answers
    And ZAC starts a new zaak
""")
def test_without_objecten_the_portal_kiss_and_zac_work(
    page: Page,
    http: requests.Session,
    urls: dict[str, str],
    podiumd_env: Environment,
    zac_zaak: Callable[..., JsonObject],
    need_bootstrap: Callable[..., None],
) -> None:
    """Without Objecten: Mijn zaken and KISS answer, and ZAC starts a zaak."""
    need_bootstrap(INWONER.name, *WIRING)
    with component_down(podiumd_env, http, "objecten"):
        portal_login(page, podiumd_env, "digid", INWONER, "/mijn-zaken/")
        assert not is_server_error(http.get(f"{urls['kiss']}/", timeout=ROOT_TIMEOUT)), "KISS fails without Objecten"
        assert zac_zaak()["identificatie"]


@pytest.mark.requires("openformulieren", "mailpit")
@pytest.mark.tc("CONT-062")
@pytest.mark.xfail(
    strict=True,
    raises=WaitTimeoutError,
    reason="[open-formulieren-2] Open Formulieren 3.5.5 and 4.0.2 queue mail with django_yubin but schedule no retry_emails: a mail that fails"
    " during an SMTP outage stays failed and is never sent; not yet reported upstream",
)
@pytest.mark.source(
    "draaiboek CONT-062",
    "With the mail server unavailable, Open Formulieren's mail is queued and sent once the outage is over.",
)
@pytest.mark.scenario("""
    Given a form in Open Formulieren that registers by e-mail
    And the mail server is stopped
    When an inwoner submits the form
    And the mail server is started again
    Then the registration mail arrives
""")
def test_form_mail_is_sent_after_a_mail_outage(
    http: requests.Session, podiumd_env: Environment, mailpit: ApiClient, registry: ResourceRegistry
) -> None:
    """A form registered by e-mail while the mail server is down is mailed once it is back."""
    slug = registry.tagged("mailstoring")
    address = f"{slug}@example.invalid"
    field = {"type": "textfield", "key": "omschrijving", "label": "Omschrijving"}
    make_form(podiumd_env, registry, slug, [field], {"backend": "email", "options": {"to_emails": [address]}})
    registry.add(f"queued mails to {address}", lambda: mail_queue(podiumd_env, "openformulieren", "delete", address))
    with component_down(podiumd_env, http, "mailpit"):
        submit(podiumd_env, http, registry, slug, {"omschrijving": slug}, timeout=REGISTRATION_TIMEOUT, registers=False)
    assert slug in received(mailpit, registry, timeout=RETRY_TIMEOUT, to=address)


@pytest.mark.requires("zac", "objecten", "openklant", "mailpit", "keycloak")
@pytest.mark.tc("CONT-061")
@pytest.mark.usefixtures("ontvangstbevestiging")
@pytest.mark.xfail(
    strict=True,
    raises=WaitTimeoutError,
    reason="[zac-3] ZAC 5.4.5 and 5.9.1 send mail directly over SMTP: during an outage it logs 'Failed to send mail' and drops it,"
    " without a queue or a retry; PZ-13091",
)
@pytest.mark.source(
    "draaiboek CONT-061", "With the mail server unavailable, ZAC's mail is queued and sent once the outage is over."
)
@pytest.mark.scenario("""
    Given the mail server is stopped
    When a productaanvraag with the inwoner's e-mail address makes ZAC start a zaak
    And ZAC fails to send the ontvangstbevestiging
    And the mail server is started again
    Then the ontvangstbevestiging with the zaaknummer arrives
""")
def test_zac_mail_is_sent_after_a_mail_outage(
    http: requests.Session,
    podiumd_env: Environment,
    objecten: ApiClient,
    openklant: ApiClient,
    openzaak_productaanvraag: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    productaanvraag_objecttype: str,
) -> None:
    """ZAC's ontvangstbevestiging for a zaak started while the mail server is down is mailed once it is back."""
    kenmerk = registry.tagged("zac-mailstoring")
    adres = f"{kenmerk}@example.invalid"
    make_submission_contact(openklant, registry, kenmerk, adres)
    zac = podiumd_env.deployment_for("zac")
    with component_down(podiumd_env, http, "mailpit"):
        make_productaanvraag(objecten, registry, productaanvraag_objecttype, productaanvraagtype, kenmerk)
        zaak = productaanvraag_zaak(openzaak_productaanvraag, registry, kenmerk)
        # ZAC sends the mail after it started the zaak; keep the mail server down until it tried.
        tried = f"Failed to send mail with subject 'Ontvangstbevestiging van zaak {zaak['identificatie']}"
        wait_until(
            lambda: tried in podiumd_env.kube.logs(zac, since="10m", container="zac"),
            timeout=PRODUCTAANVRAAG_TIMEOUT,
            description=f"ZAC's failed mail for {zaak['identificatie']}",
        )
    assert str(zaak["identificatie"]) in received(mailpit, registry, timeout=RETRY_TIMEOUT, to=adres)


@pytest.mark.requires("openklant", "zac", "keycloak")
@pytest.mark.tc("CONT-034")
@pytest.mark.source(
    "draaiboek CONT-034",
    "With Open Klant unavailable, a zaak cannot be handled and the employee sees a user-friendly error message.",
)
@pytest.mark.scenario("""
    Given a zaak in ZAC with a person as initiator
    When Open Klant is stopped
    Then ZAC fails to open the zaak with a server error
    And ZAC itself keeps answering
    And ZAC opens the zaak again once Open Klant is back
""")
def test_without_open_klant_a_zaak_with_a_person_cannot_be_opened(
    http: requests.Session, podiumd_env: Environment, zac: requests.Session, zac_zaak: Callable[..., JsonObject]
) -> None:
    """Without Open Klant ZAC cannot open a zaak whose initiator is a person, and ZAC itself stays up.

    ZAC reads the initiator's contact details from Open Klant through the edge (openklant.local). Its own answer
    is 500 with the generic message "msg.error.server.generic". When Open Klant is scaled down, ZAC's call may
    instead hang until the edge's read timeout and return 504 (observed on minikube; the exact cause is not
    established). Either outcome means the zaak does not open. Once Open Klant is back the zaak opens again.
    """
    zaak = zac_zaak()
    zac_url = podiumd_env.profile.urls["zac"]

    make_person_initiator(zac, zac_url, zaak, EREBOS)
    with component_down(podiumd_env, http, "openklant"):
        opened = zac.get(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}", timeout=DOWN_COMPONENT_TIMEOUT)
        assert opened.status_code in {HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.GATEWAY_TIMEOUT}, describe(opened)
        if opened.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
            assert opened.json().get("message") == "msg.error.server.generic"
        assert is_root_answering(zac, zac_url, ROOT_TIMEOUT), "ZAC itself fails without Open Klant"
    assert read_zaak(zac, zac_url, str(zaak["uuid"]))["identificatie"] == zaak["identificatie"]


@pytest.mark.requires("openinwoner", "openklant", "mailpit")
@pytest.mark.tc("CONT-063")
@pytest.mark.source(
    "draaiboek CONT-063",
    "With the mail server unavailable, the portal's mail is queued and sent once the outage is over.",
)
@pytest.mark.scenario("""
    Given the mail server is stopped
    When an anonymous inwoner sends a question with the contact form of Open Inwoner
    Then Open Inwoner confirms the question
    And its mail stays unsent in Open Inwoner's mail queue
    And the mail arrives once the mail server is back and the queue is retried
""")
def test_portal_mail_waits_in_the_queue_during_a_mail_outage(
    page: Page,
    http: requests.Session,
    podiumd_env: Environment,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """A contact form question during a mail outage is taken; its mail waits in Open Inwoner's queue and goes out after.

    Open Inwoner's beat retries the queue every hour; the test runs that retry itself once the server is back.
    """
    need_bootstrap("openinwoner-cms-pages", "openinwoner-openklant")
    vraag = registry.tagged("portaal-mailstoring")
    clean_up_klantcontacten(openklant, registry, QUESTION_SUBJECT, vraag)
    registry.add(f"queued mails about {vraag}", lambda: mail_queue(podiumd_env, "openinwoner", "delete", vraag))
    # mailpit.quoted would be this module's 51st imported name (WPS203).
    about_vraag = f'"{vraag}"'  # noqa: B907  # Mailpit search phrase
    forget_mails(podiumd_env, registry, about_vraag)
    with component_down(podiumd_env, http, "mailpit"):
        ask_anonymously(page, podiumd_env, QUESTION_SUBJECT, vraag, f"{vraag}@example.invalid")
        expect(
            page.get_by_text("Vraag verstuurd", exact=False).or_(page.locator(".notification")).first
        ).to_be_visible()
        statuses = wait_until(
            lambda: [
                s for s in mail_queue(podiumd_env, "openinwoner", "status", vraag) if s in {"Mislukt", "Verzonden"}
            ],
            timeout=REGISTRATION_TIMEOUT,
            description=f"Open Inwoner's attempt to mail {vraag}",
        )
        assert "Verzonden" not in statuses
    mail_queue(podiumd_env, "openinwoner", "retry", vraag)
    wait_until(
        lambda: mailpit.get("search", {"query": about_vraag}).get("messages"),
        timeout=REGISTRATION_TIMEOUT,
        description=f"mail about {vraag} in Mailpit",
    )


@pytest.mark.requires("ita", "openklant", "objecten", "mailpit", "keycloak")
@pytest.mark.tc("CONT-064")
@pytest.mark.xfail(
    strict=True,
    raises=WaitTimeoutError,
    reason="[ita-1] ITA 3.3.2 and 3.3.4 send mail straight over SMTP: during an outage it logs the SmtpException, still answers 200"
    " and drops the mail, without a queue or a retry; not yet reported upstream",
)
@pytest.mark.source(
    "draaiboek CONT-064",
    "With the mail server unavailable, Contact's (ITA) mail is queued and sent once the outage is over.",
)
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA and has taken a contactverzoek
    And the mail server is stopped
    When the KCC medewerker forwards the contactverzoek to a groep
    And the mail server is started again
    Then the groep receives the mail about the forwarded contactverzoek
""")
def test_ita_mail_is_sent_after_a_mail_outage(
    page: Page,
    http: requests.Session,
    podiumd_env: Environment,
    openklant: ApiClient,
    objecten: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """ITA's mail to the groep a contactverzoek is forwarded to during a mail outage is sent once the server is back."""
    need_bootstrap(KCC.name, "openklant-actor-kcc")
    ita = kcc_login(page, podiumd_env, "ita")
    ita_url = podiumd_env.profile.urls["ita"]
    groep = ita_calls.make_eenheid(podiumd_env, objecten, openklant, registry, "Groep", with_mailbox=True)
    adres = ita_calls.mailbox(groep)
    klantcontact = make_klantcontact(openklant, registry)
    taak = make_internetaak(openklant, registry, klantcontact, [])
    clean_up_logboek(objecten, registry, objecttype_url(podiumd_env, "Activiteitenlog"), str(taak["uuid"]))
    forget_mails(podiumd_env, registry, f'to:"{adres}"')  # noqa: B907  # Mailpit search; see about_vraag
    ita_calls.assign_to_me(ita, ita_url, taak)
    with component_down(podiumd_env, http, "mailpit"):
        forward = ita.post(f"{ita_url}/api/internetaken/{taak['uuid']}/forward", json={"groep": groep})
        expect_status(forward, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    # CronJob ita-nieuw-cv-notify mails the same address and body as "Nieuw contactverzoek - <nummer>".
    subject = f"Contactverzoek Doorgestuurd - {klantcontact['nummer']}"
    assert received(mailpit, registry, timeout=RETRY_TIMEOUT, to=adres, subject=subject)
