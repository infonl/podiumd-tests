"""Chain: a form submitted after a DigiD or eHerkenning login registers a zaak with that initiator; a cancelled login.

Ported from TA regression 158, 159 and 183. DigiD and eHerkenning are Keycloak's mock (wiring W1);
without a login Open Formulieren registers no initiator.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.names import TEST_FORM
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.browser import browser_session
from podiumd_tests.browser import cancel_login
from podiumd_tests.browser import keycloak_login
from podiumd_tests.browser import leave_login_callback
from podiumd_tests.browser import refuse_cookies
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import login_url
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import submit
from podiumd_tests.seed.openzaak import ZAKEN

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.core,
    pytest.mark.requires("openformulieren", "openzaak", "keycloak"),
]

INWONER, _, BEDRIJF = IDENTITIES
REGISTRATION_TIMEOUT = 90


def submit_after_login(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    method: str,
    user: KeycloakUser,
) -> list[JsonObject]:
    """Log in on the test form with method (digid_oidc, eherkenning_oidc), submit it; the rollen of its zaak."""
    base = podiumd_env.profile.urls["openformulieren"]
    page.goto(login_url(browser_session(page, podiumd_env), base, TEST_FORM, method))
    keycloak_login(page, user.username, podiumd_env.credentials.get(user.store_key))
    leave_login_callback(page, base, "/callback")
    # The form's SDK in the page shares the session and overwrites it with its own requests,
    # which loses the submission the API calls below put in it (403).
    page.goto("about:blank")
    status = submit(
        podiumd_env,
        browser_session(page, podiumd_env),
        registry,
        TEST_FORM,
        {"klacht_omschrijving": registry.tagged(f"{method}-klacht"), **NAW_DATA},
        timeout=REGISTRATION_TIMEOUT,
    )
    zaak = str(registered_zaak(podiumd_env, openzaak, registry, status)["url"])
    assert openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": zaak})
    return openzaak.list(f"{ZAKEN}/rollen", {"zaak": zaak})


@pytest.mark.tc("ARCH-019")
@pytest.mark.source(
    "TA regression/183-of-digid-zaak-rol.spec.ts",
    "A DigiD-logged-in inwoner's form registers a zaak with a BSN initiator role and the form's PDF report as document.",
)
@pytest.mark.scenario("""
    Given an inwoner logs in to the test form in Open Formulieren with DigiD
    When the inwoner submits the form
    Then a zaak in Open Zaak gets the form as document
    And its initiator is the inwoner, by BSN
""")
def test_digid_submission_has_the_inwoner_as_initiator(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """The zaak of a DigiD submission has a natuurlijk-persoon initiator with the inwoner's BSN and the PDF (TA reg-183)."""
    need_bootstrap("openformulieren-oidc-mock", INWONER.name)
    rollen = submit_after_login(page, podiumd_env, openzaak, registry, "digid_oidc", INWONER)
    initiators = [r for r in rollen if r.get("betrokkeneType") == "natuurlijk_persoon"]
    assert [section(r, "betrokkeneIdentificatie").get("inpBsn") for r in initiators] == [INWONER.attributes["bsn"][0]]


@pytest.mark.source(
    "TA regression/158-of-eherkenning-vestiging.spec.ts",
    "An eHerkenning submission is attributed to the vestiging within the KvK entity.",
)
@pytest.mark.source(
    "TA regression/159-of-zaak-keten.spec.ts",
    "A completed eHerkenning submission creates a zaak in Open Zaak with the company's KvK as initiator.",
)
@pytest.mark.scenario("""
    Given a company logs in to the test form in Open Formulieren with eHerkenning
    When the company submits the form
    Then a zaak in Open Zaak gets the form as document
    And its initiator is the company's vestiging, by KvK and vestigingsnummer
""")
def test_eherkenning_submission_has_the_vestiging_as_initiator(
    page: Page,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """The zaak of an eHerkenning submission has the company's vestiging as initiator (TA reg-158, reg-159)."""
    need_bootstrap("openformulieren-oidc-mock", BEDRIJF.name)
    rollen = submit_after_login(page, podiumd_env, openzaak, registry, "eherkenning_oidc", BEDRIJF)
    initiators = [section(r, "betrokkeneIdentificatie") for r in rollen if r.get("omschrijvingGeneriek") == "initiator"]
    assert [(i.get("kvkNummer"), i.get("vestigingsNummer")) for i in initiators] == [
        (BEDRIJF.attributes["kvk"][0], BEDRIJF.attributes["vestigingsnummer"][0])
    ]


@pytest.mark.source(
    "external RWS/keycloak-saml-identiteitsaanbieders cancel_response.xml",
    "A user who cancels at DigiD or eHerkenning returns to the form with a 'cancelled' message.",
)
@pytest.mark.parametrize("service", ["DigiD", "eHerkenning"])
@pytest.mark.scenario("""
    Given an inwoner or company opens the test form in Open Formulieren
    And starts to log in with DigiD or eHerkenning
    When the user cancels at DigiD or eHerkenning
    Then the form's start page says the login was cancelled
    And offers the login again
""")
def test_cancelled_login_returns_to_the_form_with_a_message(
    page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None], service: str
) -> None:
    """A cancel at the identity provider ends on the form's start page with its 'geannuleerd' message."""
    need_bootstrap("openformulieren-form", "openformulieren-oidc-mock")
    page.goto(f"{podiumd_env.profile.urls['openformulieren']}/{TEST_FORM}/")
    refuse_cookies(page)
    login = page.get_by_role("link", name=f"Inloggen met {service}")
    login.click()
    cancel_login(page)
    expect(page.get_by_role("alert")).to_contain_text(re.compile(f"inloggen met {service} geannuleerd", re.IGNORECASE))
    expect(login).to_be_visible()
