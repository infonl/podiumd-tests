"""Playwright settings for the profile's URLs, and the Keycloak login form.

In host-header mode Chromium resolves the profile hosts to the ingress IP, as the HTTP
sessions do. Chromium cannot take a CA file, so with access.ca_bundle (a local CA) it skips
certificate checks; the HTTP tests verify those certificates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.responses import url_host

if TYPE_CHECKING:
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


def keycloak_login(page: Page, username: str, password: str) -> None:
    """Fill and submit the Keycloak login form the page shows."""
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#kc-login").click()


def challenge_login(page: Page, env: Environment, app_url: str, username: str, password: str) -> requests.Session:
    """Log in to an ASP.NET app with a /api/challenge route (PABC, KISS, ITA) through Keycloak.

    The login must start as a page navigation: a fetch gets 401 and a Keycloak URL without
    `state`, and such a login never completes. The returned HTTP session carries the browser's
    cookies and reaches the profile hosts as Environment.session() does; Playwright's own
    request context resolves names without the browser's host mapping.
    """
    page.goto(app_url + "/api/challenge?returnUrl=%2F")
    keycloak_login(page, username, password)
    page.wait_for_url(lambda url: url_host(url) == url_host(app_url) and "/signin-oidc" not in url)
    http = env.session()
    for cookie in page.context.cookies():
        name, value, domain = str(cookie.get("name")), str(cookie.get("value")), cookie.get("domain") or ""
        http.cookies.set(name, value, domain=domain)  # pyright: ignore[reportUnknownMemberType]  # untyped **kwargs in the stubs
    return http
