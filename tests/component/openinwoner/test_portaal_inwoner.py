"""Open Inwoner as a logged-in inwoner: profile, notification settings, Mijn vragen, contact form, headings.

Ported from TA interaction 105 and 108, regression 96, 106, 114, 117, 163 and 165. DigiD is
Keycloak's mock (wiring W1), the pages come from wiring W5.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.openinwoner import portal_login

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.component,
    pytest.mark.ui,
    pytest.mark.requires("openinwoner", "keycloak"),
]

INWONER, INWONER2, _ = IDENTITIES


@pytest.fixture(name="portal")
def fixture_portal(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> str:
    """The portal URL, with the page logged in as the inwoner through DigiD."""
    need_bootstrap(INWONER.name, "openinwoner-oidc-mock", "openinwoner-cms-pages")
    portal_login(page, podiumd_env, "digid", INWONER)
    return podiumd_env.profile.urls["openinwoner"]


def heading(page: Page) -> str:
    """The page's first heading."""
    return page.locator("h1, h2").first.inner_text().strip()


@pytest.mark.core
def test_profile_can_be_edited(page: Page, portal: str) -> None:
    """The profile edit form offers e-mail addresses and phone numbers (TA int-105, as formsets in this Open Inwoner)."""
    page.goto(portal + "/mijn-profiel/edit/")
    expect(page.get_by_role("heading", name="Bewerk contactgegevens")).to_be_visible()
    expect(page.locator('input[name="email_addresses-TOTAL_FORMS"]').first).to_be_attached()
    expect(page.locator('input[name="phone_addresses-TOTAL_FORMS"]').first).to_be_attached()


def test_notification_setting_is_saved(page: Page, portal: str) -> None:
    """Switching the zaak notifications setting persists, and switching back too (TA reg-106, reg-165)."""
    page.goto(portal + "/mijn-profiel/notificaties/")
    setting = page.locator('input[name="cases_notifications"]')
    if not setting.count():
        pytest.skip("Open Inwoner offers no zaak notification setting here (SiteConfiguration)")
    before = setting.is_checked()
    for wanted in (not before, before):
        # The checkbox is styled away; its label toggles it.
        if setting.is_checked() != wanted:
            setting.dispatch_event("click")
        page.get_by_role("button", name="Sla wijzigingen op").first.click()
        page.goto(portal + "/mijn-profiel/notificaties/")
        assert page.locator('input[name="cases_notifications"]').is_checked() == wanted


def test_mijn_vragen_answers(page: Page, portal: str) -> None:
    """The Mijn vragen list and its second page render without an error (TA reg-117)."""
    for path in ("/mijn-zaken/contactmomenten/", "/mijn-zaken/contactmomenten/?page=2"):
        response = page.goto(portal + path)
        assert response is not None
        assert response.status < 500
        expect(page.locator("body.openinwoner-theme, .openinwoner-theme").first).to_be_attached()


@pytest.mark.parametrize(
    ("path", "words"),
    [
        ("/mijn-profiel/", "welkom|mijn profiel|profiel"),
        ("/mijn-profiel/edit/", "profiel|gegevens|aanpassen|wijzig"),
        ("/mijn-profiel/notificaties/", "notificatie|melding|voorkeur"),
        ("/search/", "zoek"),
        ("/contactformulier/", "contact|vraag"),
    ],
)
def test_page_heading_matches_its_menu_item(page: Page, portal: str, path: str, words: str) -> None:
    """Each page's heading names what its menu item promises (TA reg-163, reg-96, int-108)."""
    page.goto(portal + path)
    assert re.search(words, heading(page), re.IGNORECASE), heading(page)


def test_second_inwoner_sees_own_profile(
    page: Page, podiumd_env: Environment, portal: str, need_bootstrap: Callable[..., None]
) -> None:
    """After logging out, a second inwoner logs in to their own profile (TA reg-114)."""
    need_bootstrap(INWONER2.name)
    page.goto(portal + "/digid-oidc/logout/")
    page.context.clear_cookies()
    portal_login(page, podiumd_env, "digid", INWONER2, "/mijn-profiel/")
    expect(page).to_have_url(re.compile(r"/mijn-profiel/"))
