"""Chain: a gemeente begeleider starts a samenwerking (a plan) with an inwoner or company in Open Inwoner.

The begeleider adds the identity's account as a contact, the identity approves, and the plan the
begeleider then makes with it shows in the identity's Samenwerken.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.bootstrap.steps import OI_BEGELEIDER
from podiumd_tests.mailpit import forget_mails
from podiumd_tests.openinwoner import LOGINS
from podiumd_tests.openinwoner import begeleider_login
from podiumd_tests.openinwoner import portal_login
from podiumd_tests.openinwoner import reset_begeleider

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ui,
    pytest.mark.requires("openinwoner", "keycloak", "cluster"),
    # Every case resets the one begeleider's plans and contacts.
    pytest.mark.xdist_group("openinwoner-begeleider"),
]

CONTACTS = "/mijn-profiel/contacts/"
SAMENWERKEN = "/samenwerken/"


@pytest.mark.tc("OI-089", "OI-090")
@pytest.mark.parametrize("who", sorted(LOGINS))
def test_begeleider_starts_a_samenwerking(
    page: Page, podiumd_env: Environment, registry: ResourceRegistry, need_bootstrap: Callable[..., None], who: str
) -> None:
    """A plan the begeleider makes with the identity as contact shows in the identity's Samenwerken."""
    identity, method = LOGINS[who]
    need_bootstrap(identity.name, OI_BEGELEIDER.name, "openinwoner-oidc-mock", "openinwoner-cms-pages")
    portal = podiumd_env.profile.urls["openinwoner"]
    reset_begeleider(podiumd_env)
    registry.add("plans and contacts of the begeleider", lambda: reset_begeleider(podiumd_env))
    # Open Inwoner mails both sides about the contact request.
    forget_mails(podiumd_env, registry, f'to:"{OI_BEGELEIDER.params["email"]}"')
    forget_mails(podiumd_env, registry, f'to:"{user_email(identity.username)}" subject:"contactpersoon"')
    # The first login makes the identity's account, which the begeleider finds by its e-mail address.
    portal_login(page, podiumd_env, method, identity, CONTACTS)
    page.context.clear_cookies()

    begeleider_login(page, podiumd_env)
    page.goto(portal + CONTACTS + "create/")
    page.locator('input[name="first_name"]').fill("PodiumD")
    page.locator('input[name="last_name"]').fill(who)
    page.locator('input[name="email"]').fill(user_email(identity.username))
    page.locator('form:has(input[name="email"]) [type="submit"]').click()
    page.context.clear_cookies()

    portal_login(page, podiumd_env, method, identity, CONTACTS)
    page.locator('button[name="contact_approve"]').first.click()
    page.context.clear_cookies()

    title = registry.tagged("samenwerking")
    begeleider_login(page, podiumd_env)
    page.goto(portal + SAMENWERKEN + "create/")
    page.locator('input[name="title"]').fill(title)
    page.locator('[name="goal"]').fill("Samen een doel halen")
    # A read-only flatpickr field: set the date through flatpickr, which formats it for the form.
    end_date = (datetime.now(tz=UTC) + timedelta(days=30)).date().isoformat()
    page.locator('input[name="end_date"]').evaluate("(field, date) => field._flatpickr.setDate(date, true)", end_date)
    # The begeleider's only contact, after the reset. The checkbox is hidden behind its label,
    # which is empty for a company: its account has no name.
    page.locator('input[name="plan_contacts"]').first.dispatch_event("click")
    page.locator('form:has(input[name="title"]) [type="submit"]').click()
    page.context.clear_cookies()

    portal_login(page, podiumd_env, method, identity, SAMENWERKEN)
    expect(page.locator("main")).to_contain_text(title)
