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
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import expect_defect

if TYPE_CHECKING:
    import pytest
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

API = "/api/v1"
# Open Archiefbeheer from 2.1 runs on Django 5.2, whose admin logout accepts only POST.
ADMIN_LOGOUT_POST_ONLY = (2, 1)


def _credentials(env: Environment, role: str) -> dict[str, str]:
    return {
        "username": f"{PREFIX}-{role}",
        "password": env.credentials.get(django_secret_key("openarchiefbeheer", role)),
    }


def ui_login(page: Page, env: Environment, role: str) -> None:
    """Log the role's test user in through OAB's own login page; the page ends on the vernietigingslijsten."""
    credentials = _credentials(env, role)
    page.goto(f"{env.profile.urls['openarchiefbeheer']}/login")
    # The SPA renders the form after its own requests; filling it earlier loses the input.
    expect(page.get_by_role("button", name="Inloggen")).to_be_enabled()
    # The button is enabled before whoami sets csrftoken; a login without it gets 403 session_expired.
    # Read from the context: OAB's CSP refuses the eval of page.wait_for_function.
    wait_until(
        lambda: any(cookie.get("name") == "csrftoken" for cookie in page.context.cookies()) or None,
        timeout=10,
        interval=0.2,
        description="Open Archiefbeheer sets the csrftoken cookie",
    )
    page.get_by_label("Gebruikersnaam").fill(credentials["username"])
    page.get_by_label("Wachtwoord").fill(credentials["password"])
    page.get_by_role("button", name="Inloggen").click()
    page.wait_for_url("**/destruction-lists")


def login(env: Environment, role: str) -> requests.Session:
    """Return a session of the role's test user (bootstrap OAB_ROLES); its CSRF token rides along on every request."""
    url = env.profile.urls["openarchiefbeheer"]
    http = env.session()
    # whoami sets the csrftoken cookie that the login and every later write must echo.
    http.get(f"{url}{API}/whoami/")
    http.headers.update({"X-CSRFToken": http.cookies.get("csrftoken") or "", "Referer": f"{url}/login"})
    expect_status(
        http.post(f"{url}{API}/auth/login/", json=_credentials(env, role)), HTTPStatus.OK, HTTPStatus.NO_CONTENT
    )
    # The login rotates the token.
    http.headers["X-CSRFToken"] = http.cookies.get("csrftoken") or ""
    return http


def cache_zaken(env: Environment, urls: list[str], *, cached: bool) -> None:
    """Put zaken in OAB's zaken cache, or take them out with every destruction list holding one."""
    params: dict[str, object] = {"action": "cache" if cached else "uncache", "urls": urls}
    run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_zaken", params)


def forget_zaken(env: Environment, urls: list[str]) -> None:
    """Delete zaken from OAB's zaken cache only, as a zaak deleted in Open Zaak leaves OAB after its sync."""
    run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_zaken", {"action": "forget", "urls": urls})


def set_archive_config(env: Environment, fields: dict[str, object]) -> dict[str, object]:
    """Set fields of OAB's global ArchiveConfig; their old values, to set back."""
    old = run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_archive_config", {"fields": fields})
    return cast("dict[str, object]", old)


def destroy_now(env: Environment, lijst: str) -> None:
    """Start the destruction of a queued list now instead of on its planned date."""
    run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_destroy_now", {"uuid": lijst})


def queues_review_after_commit(env: Environment) -> bool:
    """Whether OAB queues process_review_response only after the review response is committed."""
    return bool(
        run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_review_response", {"action": "on_commit"})
    )


def process_review_response(env: Environment, lijst: str) -> bool:
    """Process the list's latest review response now; False when the list no longer waits for it."""
    params: dict[str, object] = {"action": "process", "uuid": lijst}
    return bool(run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_review_response", params))


def expect_admin_logout_bug(request: pytest.FixtureRequest, env: Environment) -> None:
    """Mark the test a strict xfail when the deployed Open Archiefbeheer is 2.1 or newer."""
    expect_defect(
        request,
        env,
        "openarchiefbeheer",
        lambda version: version >= ADMIN_LOGOUT_POST_ONLY,
        raises=AssertionError,
        reason="[open-archiefbeheer-7] Open Archiefbeheer 2.1.2: the admin's 'Log out' link sends a GET,"
        " which Django 5.2's logout answers with 405; not yet reported upstream",
    )
