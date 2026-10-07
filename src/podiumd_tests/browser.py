"""Playwright settings for the profile's URLs, and the Keycloak login form.

In host-header mode Chromium resolves the profile hosts to the ingress IP, as the HTTP
sessions do. Chromium cannot take a CA file, so with access.ca_bundle (a local CA) it skips
certificate checks; the HTTP tests verify those certificates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.responses import url_host

if TYPE_CHECKING:
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
