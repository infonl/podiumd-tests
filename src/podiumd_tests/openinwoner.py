"""Open Inwoner (the portal): a DigiD or eHerkenning login through Keycloak's mock (wiring W1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.browser import keycloak_login
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.steps import KeycloakUser
    from podiumd_tests.environment import Environment


def portal_login(page: Page, env: Environment, method: str, user: KeycloakUser, next_path: str = "/") -> None:
    """Log the test identity in with "digid" or "eherkenning"; the page ends on the portal after the callback."""
    portal = env.profile.urls["openinwoner"]
    page.goto(f"{portal}/{method}-oidc/authenticate/?next={next_path}")
    keycloak_login(page, user.username, env.credentials.get(user.store_key))
    page.wait_for_url(lambda url: url_host(url) == url_host(portal) and "-oidc/callback" not in url)


def refuse_cookies(page: Page) -> None:
    """Close the cookie banner, which otherwise lies over the page's buttons."""
    banner = page.get_by_role("button", name="Alles weigeren")
    if banner.count() and banner.first.is_visible():
        banner.first.click()
