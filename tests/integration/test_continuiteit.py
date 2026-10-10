"""Continuity: a stopped component answers no more, the others stay up and keep working, and it comes back.

Ported from TA regression 89, 124 and 144; the draaiboek's Continuïteit sheet. Each test scales a
component's main deployment to 0 and restores it afterwards.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.components import COMPONENTS
from podiumd_tests.kcc import kcc_login
from podiumd_tests.mailpit import forget_mails
from podiumd_tests.mailpit import mail_queue
from podiumd_tests.mailpit import received
from podiumd_tests.openformulieren import delete_submission
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.openformulieren import submit
from podiumd_tests.openinwoner import ask_anonymously
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import is_server_error
from podiumd_tests.responses import root_answers
from podiumd_tests.seed.objecten import clean_up_logboek
from podiumd_tests.seed.objecten import make_object
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
from podiumd_tests.zac import PRODUCTAANVRAAG_TIMEOUT
from podiumd_tests.zac import productaanvraag_zaak
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import send_with_person
from podiumd_tests.zac import zaak_body

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
# The subject of the contact form questions (bootstrap openinwoner-openklant).
QUESTION_SUBJECT = "Algemene vraag"
# Open Inwoner's Mijn zaken retries its fetch of the zaken before it shows the failure.
FETCH_RETRY_TIMEOUT_MS = 180_000
# Time a failed mail gets to be sent again after the outage.
RETRY_TIMEOUT = 8 * 60
STOPPED = ("openzaak", "openformulieren", "openklant", "opennotificaties", "openinwoner", "ita", "kiss", "zac", "omc")


@pytest.mark.parametrize("component", [requiring(c, c) for c in STOPPED])
@pytest.mark.tc("CONT-003", "CONT-004", "CONT-007", "CONT-012", "CONT-016", "CONT-020")
def test_stopped_component_harms_no_other(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment, component: str
) -> None:
    """While the component is stopped its root fails and every other root answers (TA reg-89, 124, 144)."""
    others = [
        c for c in sorted(urls) if c != component and c in COMPONENTS and root_answers(http, urls[c], ROOT_TIMEOUT)
    ]
    with component_down(podiumd_env, http, component):
        assert [c for c in others if not root_answers(http, urls[c], ROOT_TIMEOUT)] == []


def form_starts(podiumd_env: Environment, http: requests.Session, registry: ResourceRegistry) -> None:
    """Open Formulieren starts a submission of the test form; cleanup deletes it."""
    submission, _ = start_submission(http, podiumd_env.profile.urls["openformulieren"], TEST_FORM)
    registry.add(f"submission {submission['id']}", lambda: delete_submission(podiumd_env, str(submission["id"])))


@pytest.mark.requires("openzaak", "openformulieren", "openinwoner", "zac", "keycloak")
@pytest.mark.tc("CONT-025", "CONT-026", "CONT-028")
def test_without_open_zaak_the_apps_say_so(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
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
        response = page.goto(podiumd_env.profile.urls["openinwoner"] + "/mijn-zaken/")
        assert response is not None and response.status < HTTPStatus.INTERNAL_SERVER_ERROR, "Mijn zaken fails"
        # Mijn zaken loads the zaken after the page, and retries twice before it gives up.
        expect(page.get_by_text("Niet alle zaken konden worden opgehaald")).to_be_visible(
            timeout=FETCH_RETRY_TIMEOUT_MS
        )
        body = zaak_body(zac_parameters, omschrijving=registry.tagged("geen-oz"))
        refused = zac.post(f"{podiumd_env.profile.urls['zac']}/rest/zaken/zaak", json=body)
        assert refused.status_code >= HTTPStatus.BAD_REQUEST
        assert root_answers(zac, podiumd_env.profile.urls["zac"], ROOT_TIMEOUT), "ZAC itself fails"


@pytest.mark.parametrize("component", [requiring(c, c) for c in ("openklant", "opennotificaties")])
@pytest.mark.requires("openformulieren")
@pytest.mark.tc("CONT-031", "CONT-036")
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
def test_without_objecten_the_portal_kiss_and_zac_work(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
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
        assert not is_server_error(http.get(urls["kiss"] + "/", timeout=ROOT_TIMEOUT)), "KISS fails without Objecten"
        assert zac_zaak()["identificatie"]


@pytest.mark.requires("openformulieren", "mailpit")
@pytest.mark.tc("CONT-062")
@pytest.mark.xfail(
    strict=True,
    raises=WaitTimeoutError,
    reason="Open Formulieren 3.5.5 queues mail with django_yubin but schedules no retry_emails: a mail that fails"
    " during an SMTP outage stays failed and is never sent; not yet reported upstream",
)
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
    reason="ZAC 5.4.5 sends mail directly over SMTP: during an outage it logs 'Failed to send mail' and drops it,"
    " without a queue or a retry; not yet reported upstream",
)
def test_zac_mail_is_sent_after_a_mail_outage(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
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
def test_without_open_klant_a_zaak_with_a_person_cannot_be_opened(
    http: requests.Session, podiumd_env: Environment, zac: requests.Session, zac_zaak: Callable[..., JsonObject]
) -> None:
    """Without Open Klant ZAC cannot open a zaak whose initiator is a person: it shows its error message and stays up.

    ZAC reads the initiator's contact details from Open Klant; its message is the generic "Er heeft zich
    helaas een technische fout voorgedaan." Once Open Klant is back the zaak opens again.
    """
    zaak = zac_zaak()
    zac_url = podiumd_env.profile.urls["zac"]

    def make_initiator(identificatie: JsonObject) -> requests.Response:
        body = {"zaakUUID": zaak["uuid"], "betrokkeneIdentificatie": identificatie}
        return zac.patch(f"{zac_url}/rest/zaken/initiator", json=body)

    expect_status(send_with_person(zac, zac_url, EREBOS, make_initiator), HTTPStatus.OK)
    with component_down(podiumd_env, http, "openklant"):
        opened = zac.get(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}")
        assert opened.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert opened.json().get("message") == "msg.error.server.generic"
        assert root_answers(zac, zac_url, ROOT_TIMEOUT), "ZAC itself fails without Open Klant"
    assert read_zaak(zac, zac_url, str(zaak["uuid"]))["identificatie"] == zaak["identificatie"]


@pytest.mark.requires("openinwoner", "openklant", "mailpit")
@pytest.mark.tc("CONT-063")
def test_portal_mail_waits_in_the_queue_during_a_mail_outage(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
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
    forget_mails(podiumd_env, registry, f'"{vraag}"')
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
        lambda: mailpit.get("search", {"query": f'"{vraag}"'}).get("messages"),
        timeout=REGISTRATION_TIMEOUT,
        description=f"mail about {vraag} in Mailpit",
    )


@pytest.mark.requires("ita", "openklant", "objecten", "mailpit", "keycloak")
@pytest.mark.tc("CONT-064")
@pytest.mark.xfail(
    strict=True,
    raises=WaitTimeoutError,
    reason="ITA 3.3.2 sends mail straight over SMTP: during an outage it logs the SmtpException, still answers 200"
    " and drops the mail, without a queue or a retry; not yet reported upstream",
)
def test_ita_mail_is_sent_after_a_mail_outage(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
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
    groep = registry.tagged("groep")
    adres = f"{groep}@example.invalid"
    make_object(
        objecten,
        registry,
        objecttype_url(podiumd_env, "Groep"),
        {"naam": groep, "identificatie": groep, "email": adres},
    )
    registry.add(
        f"actoren of {groep}",
        lambda: [
            openklant.delete(str(a["url"])) for a in openklant.list("actoren", {"actoridentificatorObjectId": groep})
        ],
    )
    taak = make_internetaak(openklant, registry, make_klantcontact(openklant, registry), [])
    clean_up_logboek(objecten, registry, objecttype_url(podiumd_env, "Activiteitenlog"), str(taak["uuid"]))
    forget_mails(podiumd_env, registry, f'to:"{adres}"')
    expect_status(ita.post(f"{ita_url}/api/internetaken/{taak['uuid']}/aan-mij-toewijzen", json={}), 200, 201, 204)
    with component_down(podiumd_env, http, "mailpit"):
        forward = ita.post(f"{ita_url}/api/internetaken/{taak['uuid']}/forward", json={"groep": groep})
        expect_status(forward, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert received(mailpit, registry, timeout=RETRY_TIMEOUT, to=adres)
