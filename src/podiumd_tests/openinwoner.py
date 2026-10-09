"""Open Inwoner (the portal): a DigiD or eHerkenning login through Keycloak's mock (wiring W1)."""

from __future__ import annotations

import re

from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.bootstrap.steps import IDENTITIES
from podiumd_tests.bootstrap.steps import OI_BEGELEIDER
from podiumd_tests.browser import keycloak_login
from podiumd_tests.browser import refuse_cookies
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from playwright.sync_api import Locator
    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.steps import KeycloakUser
    from podiumd_tests.environment import Environment

INWONER, _, BEDRIJF = IDENTITIES
# The portal's kinds of user: their test identity and login method.
LOGINS = {"inwoner": (INWONER, "digid"), "bedrijf": (BEDRIJF, "eherkenning")}


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


def begeleider_login(page: Page, env: Environment) -> None:
    """Log the test begeleider (bootstrap OI_BEGELEIDER) in with its password.

    The login page shows the password form only when registration is allowed, so the browser
    posts it itself, with the CSRF token of the contact form page.
    """
    portal = env.profile.urls["openinwoner"]
    page.goto(portal + "/contactformulier/")
    body = {
        "csrfmiddlewaretoken": page.locator('input[name="csrfmiddlewaretoken"]').first.input_value(),
        "username": str(OI_BEGELEIDER.params["email"]),
        "password": env.credentials.get(str(OI_BEGELEIDER.store_key)),
    }
    page.evaluate(
        "([url, body]) => fetch(url, {method: 'POST', body: new URLSearchParams(body), redirect: 'manual'})",
        [portal + "/accounts/login/", body],
    )
    refuse_cookies(page)


def reset_begeleider(env: Environment) -> None:
    """Delete the test begeleider's plans and drop its contacts (snippet oi_begeleider_reset)."""
    params = {"email": OI_BEGELEIDER.params["email"]}
    run_snippet(env.kube, env.deployment_for("openinwoner"), "oi_begeleider_reset", params)


def solve_captcha(page: Page) -> None:
    """Answer the sum ("Wat is 6 - 3?") the contact form asks anonymous users."""
    question = page.locator(".captcha__check").inner_text()
    match = re.search(r"(\d+)\s*([+-])\s*(\d+)", question)
    if not match:
        msg = f"no sum in Open Inwoner's captcha: {question!r}"
        raise AssertionError(msg)
    first, operator, second = int(match[1]), match[2], int(match[3])
    page.locator('input[name="captcha"]').fill(str(first + second if operator == "+" else first - second))


def choose_document(page: Page, name: str, content: bytes) -> Locator:
    """Choose a file in the upload form on the zaak status page; returns the form's upload button."""
    upload = page.locator("#document-upload")
    upload.locator('input[name="file"]').set_input_files(
        files=[{"name": name, "mimeType": "text/plain", "buffer": content}]
    )
    return upload.get_by_role("button", name="Upload documenten")


def upload_document(page: Page, name: str, content: bytes) -> None:
    """Upload a file with the form on the zaak status page the browser shows; returns when Open Inwoner answered."""
    button = choose_document(page, name, content)
    with page.expect_response(lambda r: r.request.method == "POST" and "/document-form/" in r.url):
        button.click()


def virus_scan_enabled(env: Environment) -> bool:
    """True when Open Inwoner scans uploads with ClamAV."""
    return bool(run_snippet(env.kube, env.deployment_for("openinwoner"), "oi_virus_scan", {"action": "read"}))


def set_account(env: Environment, bsn: str, **fields: object) -> dict[str, object]:
    """Set fields of the Open Inwoner account with this BSN; their old values, to set back."""
    params: dict[str, object] = {"bsn": bsn, "fields": fields}
    return cast("dict[str, object]", run_snippet(env.kube, env.deployment_for("openinwoner"), "oi_account", params))


def set_site_configuration(env: Environment, **fields: object) -> dict[str, object]:
    """Set fields of Open Inwoner's SiteConfiguration; their old values, to set back."""
    deployment = env.deployment_for("openinwoner")
    return cast("dict[str, object]", run_snippet(env.kube, deployment, "oi_site_configuration", {"fields": fields}))


def search_data(
    env: Environment, action: str, tag: str, products: list[dict[str, object]] | None = None
) -> dict[str, Any]:
    """Seed, read or remove the search test data whose slugs and remarks start with the tag (snippet oi_search_data)."""
    params: dict[str, object] = {"action": action, "tag": tag, "products": products or []}
    return cast("dict[str, Any]", run_snippet(env.kube, env.deployment_for("openinwoner"), "oi_search_data", params))
