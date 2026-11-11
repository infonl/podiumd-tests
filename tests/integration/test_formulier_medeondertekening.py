"""Chain: a form that needs a co-signer is registered only after the co-signer signed it.

The submitter names the co-signer's e-mail address; Open Formulieren mails the co-signer a link,
the co-signer logs in with DigiD (Keycloak's mock, wiring W1), gets a one-time code by mail and signs.
"""

from __future__ import annotations

import html
import re

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.browser import keycloak_login
from podiumd_tests.browser import refuse_cookies
from podiumd_tests.mailpit import quoted
from podiumd_tests.mailpit import received
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import submit

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.requires("openformulieren", "mailpit", "keycloak", "cluster"),
    pytest.mark.source("draaiboek OF-011, OF-043", "A co-signer can be appointed."),
    pytest.mark.source(
        "draaiboek OF-012, OF-044",
        "Appointing a co-signer sends an e-mail with clear instructions to the given address.",
    ),
    pytest.mark.source(
        "draaiboek OF-045", "Appointing a co-signer also offers the co-signer to log in directly and co-sign."
    ),
    pytest.mark.source(
        "draaiboek OF-046", "Choosing to co-sign sends a code to the co-signer's e-mail address to continue signing."
    ),
]

_, COSIGNER, _ = IDENTITIES
TIMEOUT = 90
# Open Formulieren's subject of the mail with the co-signer's one-time code (Dutch submissions).
OTP_SUBJECT = "Mede-ondertekentoegangscode"


def _log_in_as_cosigner(page: Page, podiumd_env: Environment, otp_mail: Callable[[], str]) -> None:
    """Log the co-signer in with DigiD and enter the one-time code that otp_mail returns."""
    refuse_cookies(page)
    page.locator('a[href*="/digid_oidc/start"]').click()
    keycloak_login(page, COSIGNER.username, podiumd_env.credentials.get(COSIGNER.store_key))
    otp = re.search(r"is:\s*(?:<[^>]+>\s*)*([0-9-]+)", otp_mail())
    assert otp, "no code in the mail with the one-time code"
    refuse_cookies(page)
    page.get_by_label("Eénmalige toegangscode").fill(otp[1])
    page.get_by_role("button", name="Bevestigen").click()


@pytest.mark.tc("OF-011", "OF-012", "OF-043", "OF-044", "OF-045", "OF-046")
@pytest.mark.scenario("""
    Given a form in Open Formulieren that needs a co-signer
    When an inwoner submits the form with the co-signer's e-mail address
    Then the confirmation page offers to co-sign right away
    And the co-signer receives a mail with a link, and the form is not registered yet
    When the co-signer logs in with DigiD, enters the code mailed to them and signs
    Then the form is registered by e-mail
""")
def test_cosigned_form_is_registered(
    page: Page,
    http: requests.Session,
    podiumd_env: Environment,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """The co-signer gets a mail with a link, logs in, enters the code mailed to them and signs; then the form registers."""
    need_bootstrap(COSIGNER.name, "openformulieren-oidc-mock")
    slug = registry.tagged("medeondertekening")
    cosigner = f"{slug}-cosigner@example.invalid"
    registratie = f"{slug}-registratie@example.invalid"
    components = [
        {"type": "textfield", "key": "omschrijving", "label": "Omschrijving"},
        {"type": "cosign", "key": "cosign", "label": "Medeondertekenaar", "authPlugin": "digid_oidc"},
    ]
    registration = {"backend": "email", "options": {"to_emails": [registratie]}}
    make_form(podiumd_env, registry, slug, components, registration, ("digid_oidc",))
    omschrijving = registry.tagged("ondertekend")
    data = {"omschrijving": omschrijving, "cosign": cosigner}
    status = submit(podiumd_env, http, registry, slug, data, timeout=TIMEOUT, registers=False)

    # The submitter can let the co-signer sign right away, on the confirmation page.
    assert "Nu mede-ondertekenen" in str(status.get("confirmationPageContent"))

    request = received(mailpit, registry, timeout=TIMEOUT, to=cosigner)
    link = re.search(r'href="([^"]+)"', request)
    assert link, "no link in the co-sign request"
    assert not mailpit.get("search", {"query": f"to:{quoted(registratie)}"}).get("messages"), (
        "registered before co-signing"
    )
    page.goto(html.unescape(link[1]))
    _log_in_as_cosigner(
        page, podiumd_env, lambda: received(mailpit, registry, timeout=TIMEOUT, to=cosigner, subject=OTP_SUBJECT)
    )
    expect(page.get_by_text(omschrijving)).to_be_visible()
    page.get_by_role("checkbox").check()
    page.get_by_role("button", name=re.compile(r"Confirm|Bevestigen")).click()
    assert omschrijving in received(mailpit, registry, timeout=TIMEOUT, to=registratie)
