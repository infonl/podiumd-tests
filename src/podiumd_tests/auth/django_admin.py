"""Log in to a Maykin app's Django admin with a local account. Ported from podiumd-minikube test_django_admin_login.py.

The admin login is a two-factor wizard (step "auth"); Open Formulieren redirects to its
classic login, so the form is posted to wherever /admin/login/ ends up.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

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
