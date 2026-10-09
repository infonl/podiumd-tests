"""Continuity: a stopped component answers no more, the others stay up and keep working, and it comes back.

Ported from TA regression 89, 124 and 144; the draaiboek's Continuïteit sheet. Each test scales a
component's main deployment to 0 and restores it afterwards.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.components import COMPONENTS
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.mailpit import received
from podiumd_tests.openformulieren import delete_submission
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import start_submission
from podiumd_tests.openformulieren import submit
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import is_server_error
from podiumd_tests.responses import root_answers
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.openklant import make_submission_contact
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import ROOT_TIMEOUT
from podiumd_tests.workloads import component_down
from podiumd_tests.zac import PRODUCTAANVRAAG_TIMEOUT
from podiumd_tests.zac import productaanvraag_zaak
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
    deployment = podiumd_env.deployment_for("openformulieren")
    registry.add(
        f"queued mails to {address}",
        lambda: run_snippet(podiumd_env.kube, deployment, "openformulieren_mail_queue", {"address": address}),
    )
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
