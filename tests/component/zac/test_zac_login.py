"""ZAC in a browser: the OIDC login through Keycloak ends on a rendered dashboard. Ported from MK test_browser.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.browser import keycloak_login
from podiumd_tests.browser import redirect_login

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

# Not strict: the race hits about 1 in 31 runs.
ZAC_7 = pytest.mark.xfail(
    strict=False,
    reason="[zac-7] ZAC 5.9.1 with Keycloak 26.8.1: after logout Keycloak can hand out a code of the session it is"
    " removing (CODE_TO_TOKEN_ERROR invalid_code), and ZAC answers 403 (Geen toestemming); not yet reported upstream",
)


def log_in_and_out(page: Page, env: Environment, zac_url: str) -> None:
    """The test admin logs in to ZAC and out through the account menu, ending on Keycloak's login form."""
    redirect_login(page, env, zac_url, ADMIN.username, env.credentials.get(ADMIN.store_key))
    page.get_by_role("button", name="Gebruikers profiel").click()
    page.get_by_role("menuitem", name="Uitloggen").click()
    expect(page.locator("#kc-form-login")).to_be_visible()


pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.core, pytest.mark.requires("zac", "keycloak")]


@pytest.mark.tc("ZAC-002")
@pytest.mark.source(
    "MK test_browser.py",
    "Proves ZAC's SPA renders for a real browser after the Keycloak login, which an HTTP status check cannot catch.",
)
@pytest.mark.source("draaiboek ZAC-002", "Users log in with their username and password; the dashboard loads.")
@pytest.mark.source("ZAC features/1-login.feature", "Bob logs in to ZAC and sees the dashboard.")
@pytest.mark.scenario("""
    Given the test admin is not logged in to ZAC
    When the admin logs in through Keycloak
    Then ZAC shows its dashboard
""")
def test_login_shows_the_dashboard(
    page: Page, podiumd_env: Environment, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """The test admin logs in through Keycloak and ZAC renders its dashboard (a blank SPA also answers 200)."""
    need_bootstrap(ADMIN.name)
    redirect_login(page, podiumd_env, urls["zac"], ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
    # The navigation only renders once the SPA has loaded the user's rights.
    expect(page.get_by_role("button", name="Dashboard", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Menu voor zaken", exact=True)).to_be_visible()


@pytest.mark.tc("ZAC-003")
@pytest.mark.source("draaiboek ZAC-003", "Users can log out, which returns them to the login screen.")
@pytest.mark.source(
    "ZAC features/1-login.feature", "Bob logs out through the user profile menu and sees the sign-in page."
)
@ZAC_7
@pytest.mark.scenario("""
    Given the test admin is logged in to ZAC
    When the admin chooses Uitloggen in the account menu
    Then the browser shows Keycloak's login form
""")
def test_logout_ends_the_session(
    page: Page, podiumd_env: Environment, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """Uitloggen in the account menu ends the session: the browser ends on Keycloak's login form."""
    need_bootstrap(ADMIN.name)
    log_in_and_out(page, podiumd_env, urls["zac"])


@pytest.mark.source("ZAC features/1-login.feature", "Bob logs back in after logging out and sees the dashboard.")
@ZAC_7
@pytest.mark.scenario("""
    Given the test admin logged in to ZAC and logged out again
    When the admin logs in once more through Keycloak
    Then ZAC shows its dashboard
""")
def test_login_after_logout_shows_the_dashboard(
    page: Page, podiumd_env: Environment, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """A second login after Uitloggen reaches the dashboard: ZAC does not refuse the new session (zac-7)."""
    need_bootstrap(ADMIN.name)
    log_in_and_out(page, podiumd_env, urls["zac"])
    redirect_login(page, podiumd_env, urls["zac"], ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
    expect(page.get_by_role("button", name="Dashboard", exact=True)).to_be_visible()


@pytest.mark.source(
    "ZAC bdd/@login/@login.feature",
    "A failed login shows 'Invalid username or password.' and gives no access to the dashboard.",
)
@pytest.mark.scenario("""
    Given a user that Keycloak does not know
    When the user tries to log in to ZAC
    Then Keycloak's login form shows "Invalid username or password."
    And the ZAC dashboard stays out of reach
""")
def test_unknown_user_stays_on_the_login_form(page: Page, urls: dict[str, str]) -> None:
    """Keycloak refuses a user it does not know with an error on its login form; ZAC stays out of reach."""
    page.goto(urls["zac"] + "/")
    keycloak_login(page, f"{PREFIX}-unknown", "wrong")
    # Keycloak's themes mark the refused field invalid; the message text depends on the locale.
    expect(page.locator("#username")).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#kc-form-login")).to_be_visible()
