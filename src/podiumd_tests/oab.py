"""Open Archiefbeheer: a local login per role (API, UI), its zaken cache, its ArchiveConfig and list destruction."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from playwright.sync_api import expect

from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.steps import django_secret_key
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

API = "/api/v1"


def _credentials(env: Environment, role: str) -> dict[str, str]:
    return {
        "username": f"{PREFIX}-{role}",
        "password": env.credentials.get(django_secret_key("openarchiefbeheer", role)),
    }


def ui_login(page: Page, env: Environment, role: str) -> None:
    """Log the role's test user in through OAB's own login page; the page ends on the vernietigingslijsten."""
    credentials = _credentials(env, role)
    page.goto(env.profile.urls["openarchiefbeheer"] + "/login")
    # The SPA renders the form after its own requests; filling it earlier loses the input.
    expect(page.get_by_role("button", name="Inloggen")).to_be_enabled()
    page.get_by_label("Gebruikersnaam").fill(credentials["username"])
    page.get_by_label("Wachtwoord").fill(credentials["password"])
    page.get_by_role("button", name="Inloggen").click()
    page.wait_for_url("**/destruction-lists")


def login(env: Environment, role: str) -> requests.Session:
    """A session of the role's test user (bootstrap OAB_ROLES); its CSRF token rides along on every request."""
    url = env.profile.urls["openarchiefbeheer"]
    http = env.session()
    # whoami sets the csrftoken cookie that the login and every later write must echo.
    http.get(url + API + "/whoami/")
    http.headers.update({"X-CSRFToken": http.cookies.get("csrftoken") or "", "Referer": url + "/login"})
    expect_status(
        http.post(url + API + "/auth/login/", json=_credentials(env, role)), HTTPStatus.OK, HTTPStatus.NO_CONTENT
    )
    # The login rotates the token.
    http.headers["X-CSRFToken"] = http.cookies.get("csrftoken") or ""
    return http


def cache_zaken(env: Environment, urls: list[str], *, cached: bool) -> None:
    """Put zaken in OAB's zaken cache, or take them out with every destruction list holding one."""
    params: dict[str, object] = {"action": "cache" if cached else "uncache", "urls": urls}
    run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_zaken", params)


def set_archive_config(env: Environment, fields: dict[str, object]) -> dict[str, object]:
    """Set fields of OAB's global ArchiveConfig; their old values, to set back."""
    old = run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_archive_config", {"fields": fields})
    return cast("dict[str, object]", old)


def destroy_now(env: Environment, lijst: str) -> None:
    """Start the destruction of a queued list now instead of on its planned date."""
    run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_destroy_now", {"uuid": lijst})
