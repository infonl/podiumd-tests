"""Log in to a Maykin app's Django admin with a local account. Ported from podiumd-minikube test_django_admin_login.py.

The admin login is a two-factor wizard (step "auth"); Open Formulieren redirects to its
classic login, so the form is posted to wherever /admin/login/ ends up.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import struct
import time

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import DJANGO_ADMINS
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.environment import Environment

CSRF = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
STEP = re.compile(r'name="admin_login_view-current_step" value="([^"]+)"')
NEXT = re.compile(r'name="next" value="([^"]*)"')
TOTP_STEP, TOTP_DIGITS = 30, 6
# Apps whose user model logs in with the email instead of a username.
EMAIL_LOGIN = frozenset(("openinwoner",))


class AdminLoginError(AssertionError):
    """The login form is not what this helper expects. An AssertionError for pytest."""


def admin_login(session: requests.Session, base_url: str, username: str, password: str) -> requests.Response:
    """Submit the admin login form, and its token step when the app asks for one; the page it lands on.

    The token is the TOTP of the device bootstrap gives the user (django_user snippet, totp).
    """
    page = expect_status(session.get(f"{base_url}/admin/login/"), 200)
    response = _submit_step(session, base_url, page, {"auth-username": username, "auth-password": password})
    step = STEP.search(response.text)
    if step and step.group(1) == "token":
        response = _submit_step(session, base_url, response, {"token-otp_token": totp(password_totp_key(password))})
    return response


def _submit_step(
    session: requests.Session, base_url: str, page: requests.Response, fields: dict[str, str]
) -> requests.Response:
    """Post one step of the login wizard on page with fields."""
    csrf, step = CSRF.search(page.text), STEP.search(page.text)
    if not csrf or not step:
        msg = f"{page.url}: no CSRF token or two-factor step field in the login form"
        raise AdminLoginError(msg)
    following = NEXT.search(page.text)
    data = {
        "csrfmiddlewaretoken": csrf.group(1),
        "admin_login_view-current_step": step.group(1),
        **fields,
        "next": following.group(1) if following else "",
    }
    return session.post(page.url, data=data, headers={"Referer": page.url, "Origin": base_url})


def password_totp_key(password: str) -> str:
    """Return the hex TOTP key the django_user snippet derives from a password."""
    return hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest()


def totp(key_hex: str, now: float | None = None) -> str:
    """Return the RFC 6238 code of a hex key: SHA-1, 30 s steps, 6 digits (django_otp's defaults)."""
    moment = time.time() if now is None else now
    counter = int(moment // TOTP_STEP)
    digest = hmac.new(bytes.fromhex(key_hex), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0xF
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 10**TOTP_DIGITS:0{TOTP_DIGITS}d}"


def is_logged_in(response: requests.Response, username: str) -> bool:
    """Return True when the page shows the admin for username, and no login form."""
    body = re.sub(r"\s+", " ", response.text)
    return response.ok and f"<strong>{username}</strong>" in body and 'name="auth-username"' not in body


def superuser_login(
    env: Environment, need_bootstrap: Callable[..., None], component: str
) -> tuple[requests.Session, requests.Response, str]:
    """Return a session logged in to the app's admin as the test superuser, the page it landed on, and its login.

    Skips where the admin logs in through Keycloak only (settings.django_admin_sso_only).
    """
    if component in env.profile.settings.get("django_admin_sso_only", "").split(","):
        pytest.skip(f"{component}'s admin logs in through Keycloak only (settings.django_admin_sso_only)")
    step = DJANGO_ADMINS[component]
    need_bootstrap(step.name)
    login = str(step.params["email" if component in EMAIL_LOGIN else "username"])
    password = env.credentials.get(str(step.store_key))
    http = env.session()
    return http, admin_login(http, env.profile.urls[component], login, password), login
