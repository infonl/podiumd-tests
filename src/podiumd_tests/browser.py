"""Playwright settings for the profile's URLs, and the Keycloak login form.

In host-header mode Chromium resolves the profile hosts to the ingress IP, as the HTTP
sessions do. Chromium cannot take a CA file, so with access.ca_bundle (a local CA) it skips
certificate checks; the HTTP tests verify those certificates.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from playwright.sync_api import sync_playwright

from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from collections.abc import Generator

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment


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
            yield browser.new_context(**context_args(env)).new_page()  # pyright: ignore[reportArgumentType]
        finally:
            browser.close()


def keycloak_login(page: Page, username: str, password: str) -> None:
    """Fill and submit the Keycloak login form the page shows."""
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#kc-login").click()


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
    page.goto(app_url + "/api/challenge?returnUrl=%2F")
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


def refuse_cookies(page: Page) -> None:
    """Close the cookie banner of Open Inwoner or Open Formulieren, which otherwise lies over the page's buttons."""
    banner = page.get_by_role("button", name="Alles weigeren")
    if banner.count() and banner.first.is_visible():
        banner.first.click()
