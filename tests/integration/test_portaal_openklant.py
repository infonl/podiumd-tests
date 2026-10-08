"""Chain: Open Inwoner with Open Klant 2 as klantensysteem: a question from Mijn vragen, a profile e-mail address.

Ported from TA interaction 182 and regression 179. Open Inwoner reaches Open Klant with its own token (wiring
W6); the contact flow sends questions to the KCC actor (W8). At login Open Inwoner makes a
partij for the inwoner's BSN; the test removes it again if it made one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.openinwoner import set_account_email
from podiumd_tests.seed.openklant import clean_up_new_partijen
from podiumd_tests.seed.openklant import delete_klantcontact_tree
from podiumd_tests.seed.openklant import partijen_of

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.core,
    pytest.mark.requires("openinwoner", "openklant", "keycloak"),
]

INWONER = IDENTITIES[0]
SUBJECT = "Algemene vraag"


def test_question_shows_in_mijn_vragen(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """A question asked in Mijn vragen becomes a klantcontact in Open Klant and is listed, unanswered (TA int-182)."""
    need_bootstrap(INWONER.name, "openinwoner-oidc-mock", "openinwoner-cms-pages", "openinwoner-openklant")
    clean_up_new_partijen(openklant, registry, INWONER.attributes["bsn"][0])
    vraag = registry.tagged("vraag")

    def delete_question() -> None:
        for klantcontact in openklant.list("klantcontacten", {"onderwerp": SUBJECT}):
            if klantcontact.get("inhoud") == vraag:
                delete_klantcontact_tree(openklant, str(klantcontact["url"]))

    registry.add(f"question {vraag}", delete_question)
    portal_login(page, podiumd_env, "digid", INWONER, "/mijn-zaken/contactmomenten/")
    page.locator('select[name="subject"]').select_option(label=SUBJECT)
    page.locator('textarea[name="question"]').fill(vraag)
    email = page.locator('form:has(textarea[name="question"]) input[name="email"]')
    if email.count():
        email.first.fill(user_email(INWONER.username))
    page.locator("#submit_question").click()
    expect(page.get_by_text("Vraag verstuurd", exact=False).or_(page.locator(".notification")).first).to_be_visible()
    # The list does not refresh after submitting.
    page.goto(podiumd_env.profile.urls["openinwoner"] + "/mijn-zaken/contactmomenten/")
    card = page.locator(".card", has_text=vraag)
    expect(card).to_be_visible()
    expect(card).to_contain_text("Onbeantwoord")


def test_profile_email_reaches_open_klant(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    openklant: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """An e-mail address saved in the profile becomes a digitaal adres of the inwoner's partij (TA reg-179)."""
    need_bootstrap(INWONER.name, "openinwoner-oidc-mock", "openinwoner-cms-pages", "openinwoner-openklant")
    bsn = INWONER.attributes["bsn"][0]
    clean_up_new_partijen(openklant, registry, bsn)
    adres = f"{registry.tagged('profiel')}@example.invalid"
    # The partij may predate the test (an earlier login made it); its new adres goes anyway. The
    # account keeps the address and every later login sends it again: set it back first.
    registry.add(
        f"digitaal adres {adres}",
        lambda: [openklant.delete(str(a["url"])) for a in openklant.list("digitaleadressen", {"adres": adres})],
    )
    registry.add(f"e-mail of account {bsn}", lambda: set_account_email(podiumd_env, bsn, user_email(INWONER.username)))
    portal_login(page, podiumd_env, "digid", INWONER, "/mijn-profiel/edit/")
    page.locator('input[name="email_addresses-0-value"]').first.fill(adres)
    page.get_by_role("button", name="Sla wijzigingen op").first.click()
    page.wait_for_url(lambda url: "/mijn-profiel/edit/" not in url)
    adressen = [
        str(a.get("adres"))
        for partij in partijen_of(openklant, bsn)
        for a in openklant.list("digitaleadressen", {"verstrektDoorPartij__uuid": partij.rsplit("/", 1)[-1]})
    ]
    assert adres in adressen
