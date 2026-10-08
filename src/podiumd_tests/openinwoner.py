"""Open Inwoner (the portal): a DigiD or eHerkenning login through Keycloak's mock (wiring W1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.browser import keycloak_login
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.steps import KeycloakUser
    from podiumd_tests.environment import Environment


def portal_login(page: Page, env: Environment, method: str, user: KeycloakUser, next_path: str = "/") -> None:
    """Log the test identity in with "digid" or "eherkenning"; the page ends on the portal, cookie banner closed."""
    portal = env.profile.urls["openinwoner"]
    page.goto(f"{portal}/{method}-oidc/authenticate/?next={next_path}")
    keycloak_login(page, user.username, env.credentials.get(user.store_key))
    page.wait_for_url(lambda url: url_host(url) == url_host(portal) and "-oidc/callback" not in url)
    refuse_cookies(page)
    if "/register/necessary/" in page.url:
        # A first eHerkenning login makes a new account that still needs an e-mail address.
        page.locator('input[name="email"]').fill(user_email(user.username))
        page.get_by_role("button", name="Voltooi registratie").click()
        page.wait_for_url(lambda url: "/register/necessary/" not in url)
        # Open Inwoner ignores `next` after the registration.
        page.goto(portal + next_path)


def refuse_cookies(page: Page) -> None:
    """Close the cookie banner, which otherwise lies over the page's buttons."""
    banner = page.get_by_role("button", name="Alles weigeren")
    if banner.count() and banner.first.is_visible():
        banner.first.click()


def upload_document(page: Page, name: str, content: bytes) -> None:
    """Upload a file with the form on the zaak status page the browser shows; returns when Open Inwoner answered."""
    upload = page.locator("#document-upload")
    upload.locator('input[name="file"]').set_input_files(
        files=[{"name": name, "mimeType": "text/plain", "buffer": content}]
    )
    with page.expect_response(lambda r: r.request.method == "POST" and "/document-form/" in r.url):
        upload.get_by_role("button", name="Upload documenten").click()


def virus_scan_enabled(env: Environment) -> bool:
    """True when Open Inwoner scans uploads with ClamAV."""
    return bool(run_snippet(env.kube, env.deployment_for("openinwoner"), "oi_virus_scan", {}))


def set_account_email(env: Environment, bsn: str, email: str) -> None:
    """Set the e-mail of the Open Inwoner account with this BSN; a later login sends it to Open Klant."""
    run_snippet(env.kube, env.deployment_for("openinwoner"), "oi_account_email", {"bsn": bsn, "email": email})
