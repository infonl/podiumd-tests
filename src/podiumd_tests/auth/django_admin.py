"""Log in to a Maykin app's Django admin with a local account. Ported from podiumd-minikube test_django_admin_login.py.

The admin login is a two-factor wizard (step "auth"); Open Formulieren redirects to its
classic login, so the form is posted to wherever /admin/login/ ends up.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment

CSRF = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
STEP = re.compile(r'name="admin_login_view-current_step" value="([^"]+)"')
NEXT = re.compile(r'name="next" value="([^"]*)"')


class AdminLoginError(AssertionError):
    """The login form is not what this helper expects. An AssertionError for pytest."""


def admin_login(session: requests.Session, base_url: str, username: str, password: str) -> requests.Response:
    """Submit the admin login form; the response of the page it lands on."""
    page = expect_status(session.get(f"{base_url}/admin/login/"), 200)
    csrf, step = CSRF.search(page.text), STEP.search(page.text)
    if not csrf or not step:
        msg = f"{page.url}: no CSRF token or two-factor step field in the login form"
        raise AdminLoginError(msg)
    following = NEXT.search(page.text)
    data = {
        "csrfmiddlewaretoken": csrf.group(1),
        "admin_login_view-current_step": step.group(1),
        "auth-username": username,
        "auth-password": password,
        "next": following.group(1) if following else "",
    }
    return session.post(page.url, data=data, headers={"Referer": page.url, "Origin": base_url})


def is_logged_in(response: requests.Response, username: str) -> bool:
    """True when the page shows the admin for username, and no login form."""
    body = re.sub(r"\s+", " ", response.text)
    return response.ok and f"<strong>{username}</strong>" in body and 'name="auth-username"' not in body


def superuser_login(
    env: Environment, credentials: SecretResolver, component: str
) -> tuple[requests.Session, requests.Response]:
    """A session logged in to the app's admin as its local superuser, with the page it landed on.

    Skips where the admin logs in through Keycloak only (settings.django_admin_sso_only) or there is no local account.
    """
    if component in env.profile.settings.get("django_admin_sso_only", "").split(","):
        pytest.skip(f"{component}'s admin logs in through Keycloak only (settings.django_admin_sso_only)")
    username, password = credentials.optional("django_admin_username"), credentials.optional("django_admin_password")
    if not username or not password:
        pytest.skip("no secrets django_admin_username/password: admin login goes through SSO here")
    http = env.session()
    return http, admin_login(http, env.profile.urls[component], username, password)
