"""Playwright settings for the profile's URLs, and the Keycloak login form.

In host-header mode Chromium resolves the profile hosts to the ingress IP, as the HTTP
sessions do. Chromium cannot take a CA file, so with access.ca_bundle (a local CA) it skips
certificate checks; the HTTP tests verify those certificates.
"""

from __future__ import annotations

import warnings

from contextlib import contextmanager
from itertools import count
from typing import TYPE_CHECKING
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from podiumd_tests.auth.keycloak import one_login_at_a_time
from podiumd_tests.auth.keycloak import totp
from podiumd_tests.oidc import CHALLENGE
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator

    import requests

    from playwright.sync_api import Page
    from playwright.sync_api import Response

    from podiumd_tests.environment import Environment


# Chromium aborts a navigation when a host network interface changes (VPN, Wi-Fi, a Docker container).
NETWORK_CHANGED = "net::ERR_NETWORK_CHANGED"
NETWORK_RETRIES = 2
NETWORK_PAUSE_MS = 1000


def retry_network_change[T](page: Page, navigate: Callable[[], T], what: str) -> T:
    """Run a navigation; repeat it up to NETWORK_RETRIES times when a host network change aborted it."""
    for attempt in count(1):
        try:
            return navigate()
        except PlaywrightError as exc:
            if NETWORK_CHANGED not in exc.message or attempt > NETWORK_RETRIES:
                raise
            warnings.warn(f"{what}: {NETWORK_CHANGED}, retry {attempt} of {NETWORK_RETRIES}", stacklevel=2)
            page.wait_for_timeout(NETWORK_PAUSE_MS)
    raise AssertionError  # unreachable: count() never ends


def guard_navigation(page: Page) -> Page:
    """The page, whose goto and reload are repeated when a host network change aborted them."""
    goto, reload = page.goto, page.reload

    def retried_goto(url: str, **kwargs: Any) -> Response | None:
        return retry_network_change(page, lambda: goto(url, **kwargs), f"goto {url}")

    def retried_reload(**kwargs: Any) -> Response | None:
        return retry_network_change(page, lambda: reload(**kwargs), f"reload {page.url}")

    # Instance attributes over the bound methods: every caller of page.goto gets the retry.
    setattr(page, "goto", retried_goto)  # noqa: B010
    setattr(page, "reload", retried_reload)  # noqa: B010
    return page


def launch_args(env: Environment) -> list[str]:
    """Chromium arguments: map every profile host to the ingress IP in host-header mode."""
    ip = env.ingress_ip()
    if ip is None:
        return []
    hosts = sorted({url_host(u) for u in env.profile.urls.values()})
    return ["--host-resolver-rules=" + ",".join(f"MAP {h} {ip}" for h in hosts)]


def context_args(env: Environment) -> dict[str, object]:
    """Browser context options: skip certificate checks only for a local CA."""
    return {"ignore_https_errors": True} if env.profile.access.ca_bundle else {}


@contextmanager
def headless_page(env: Environment) -> Generator[Page]:
    """A page in headless Chromium with the profile's settings, outside pytest (bootstrap, seed-volume)."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=launch_args(env))
        try:
            yield guard_navigation(browser.new_context(**context_args(env)).new_page())  # pyright: ignore[reportArgumentType]
        finally:
            browser.close()


def keycloak_login(page: Page, username: str, password: str) -> None:
    """Fill and submit the Keycloak login form the page shows."""

    def submit() -> None:
        page.locator("#username").fill(username)
        page.locator("#password").fill(password)
        # Keycloak checks the login during the form's POST, the navigation the click starts.
        with one_login_at_a_time(username), page.expect_navigation():
            page.locator("#kc-login").click()

    retry_network_change(page, submit, f"Keycloak login of {username}")


def configure_totp(page: Page) -> None:
    """Complete Keycloak's CONFIGURE_TOTP required action the page shows, with the key it offers."""
    page.get_by_role("link", name="Unable to scan?").click()
    page.locator("#totp").fill(totp(page.locator("#kc-totp-secret-key").inner_text()))
    with page.expect_navigation():
        page.locator("#saveTOTPBtn").click()


def redirect_login(page: Page, env: Environment, app_url: str, username: str, password: str) -> requests.Session:
    """Log in to an app whose pages redirect to Keycloak (ZAC); returns browser_session(page, env)."""
    page.goto(app_url + "/")
    keycloak_login(page, username, password)
    page.wait_for_url(lambda url: url_host(url) == url_host(app_url))
    return browser_session(page, env)


def challenge_login(page: Page, env: Environment, app_url: str, username: str, password: str) -> requests.Session:
    """Log in to an ASP.NET app with a /api/challenge route (PABC, KISS, ITA) through Keycloak.

    The login must start as a page navigation: a fetch gets 401 and a Keycloak URL without
    `state`, and such a login never completes. Returns browser_session(page, env).
    """
    page.goto(app_url + CHALLENGE)
    keycloak_login(page, username, password)
    page.wait_for_url(lambda url: url_host(url) == url_host(app_url) and "/signin-oidc" not in url)
    return browser_session(page, env)


def browser_session(page: Page, env: Environment) -> requests.Session:
    """Environment.session() with the browser's cookies, e.g. a login session.

    Playwright's own request context resolves names without the browser's host mapping.
    """
    http = env.session()
    for cookie in page.context.cookies():
        name, value, domain = str(cookie.get("name")), str(cookie.get("value")), cookie.get("domain") or ""
        http.cookies.set(name, value, domain=domain)  # pyright: ignore[reportUnknownMemberType]  # untyped **kwargs in the stubs
    return http


def share_cookies(http: requests.Session, page: Page) -> None:
    """Give the browser the session's cookies, e.g. a login made without a browser (the reverse of browser_session)."""
    cookies = [
        {"name": c.name, "value": str(c.value), "domain": c.domain, "path": c.path or "/"}
        for c in http.cookies
        if c.domain
    ]
    page.context.add_cookies(cookies)  # pyright: ignore[reportArgumentType]  # Playwright's TypedDict


def refuse_cookies(page: Page) -> None:
    """Close the cookie banner of Open Inwoner or Open Formulieren, which otherwise lies over the page's buttons."""
    banner = page.get_by_role("button", name="Alles weigeren")
    if banner.count() and banner.first.is_visible():
        banner.first.click()
