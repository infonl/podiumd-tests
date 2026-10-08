"""Open Archiefbeheer: a local login per role, its zaken cache, its ArchiveConfig and the destruction of a list."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.steps import django_password_key
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment

API = "/api/v1"


def login(env: Environment, role: str) -> requests.Session:
    """A session of the role's test user (bootstrap OAB_ROLES); its CSRF token rides along on every request."""
    url = env.profile.urls["openarchiefbeheer"]
    http = env.session()
    # whoami sets the csrftoken cookie that the login and every later write must echo.
    http.get(url + API + "/whoami/")
    http.headers.update({"X-CSRFToken": http.cookies.get("csrftoken") or "", "Referer": url + "/login"})
    password = env.credentials.get(django_password_key("openarchiefbeheer", role))
    credentials = {"username": f"{PREFIX}-{role}", "password": password}
    expect_status(http.post(url + API + "/auth/login/", json=credentials), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
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
