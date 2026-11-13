"""Open Archiefbeheer: a local login per role (API, UI), its zaken cache, its ArchiveConfig and list destruction."""

from __future__ import annotations

import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from playwright.sync_api import expect

from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.steps import django_secret_key
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import expect_defect

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

    # A logged-in session per role (login).
    Sessions = Callable[[str], requests.Session]

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


def set_config(env: Environment, model: str, fields: dict[str, object]) -> dict[str, object]:
    """Set fields of OAB's global ArchiveConfig or EmailConfig; their old values, to set back."""
    params: dict[str, object] = {"model": model, "fields": fields}
    old = run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_config", params)
    return cast("dict[str, object]", old)


def destroy_now(env: Environment, lijst: str) -> None:
    """Start the destruction of a queued list now instead of on its planned date."""
    run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_destroy_now", {"uuid": lijst})


def is_review_queued_after_commit(env: Environment) -> bool:
    """Whether OAB queues process_review_response only after the review response is committed."""
    return bool(
        run_snippet(env.kube, env.deployment_for("openarchiefbeheer"), "oab_review_response", {"action": "on_commit"})
    )


def process_review_response(env: Environment, lijst: str) -> bool:  # noqa: FNE005  # runs the OAB task
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


def user_pk(oab: Sessions, api: str, role: str, user: str | None = None) -> int:
    """Return the pk of a test user (default: the role's own) that OAB lists for the assignee role."""
    filter_role = {"reviewer": "main_reviewer", "coreviewer": "co_reviewer"}.get(role, role)
    users = expect_status(oab("recordmanager").get(f"{api}/users/", params={"role": filter_role}), HTTPStatus.OK)
    suffix = f"-{user or role}"
    found = (item for item in entries(users.json()) if str(item["username"]).endswith(suffix))
    return int(str(next(found)["pk"]))


def list_status(oab: Sessions, api: str, lijst: str) -> str:
    """Return the list's status, as the record manager sees it."""
    return str(
        expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()["status"]
    )


def new_list(
    oab: Sessions,
    api: str,
    zaak: JsonObject | list[JsonObject],
    registry: ResourceRegistry,
    *,
    ready: bool = True,
) -> str:
    """Create a vernietigingslijst of the zaken for the test reviewer, by default ready to review; its uuid."""
    zaken = zaak if isinstance(zaak, list) else [zaak]
    body = {
        # OAB requires unique names, and the run tag is shared by all workers.
        "name": registry.tagged(f"vernietigingslijst-{secrets.token_hex(3)}"),
        "comment": "podiumd-tests",
        "containsSensitiveInfo": False,
        "add": [{"zaak": item["url"]} for item in zaken],
        "reviewer": {"user": user_pk(oab, api, "reviewer")},
    }
    created = expect_status(
        oab("recordmanager").post(f"{api}/destruction-lists/", json=body), HTTPStatus.CREATED
    ).json()
    lijst = str(created["uuid"])
    if ready:
        expect_status(
            oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/mark_ready_review/", json={}),
            HTTPStatus.CREATED,
            HTTPStatus.OK,
        )
    return lijst


def make_final(oab: Sessions, api: str, lijst: str) -> requests.Response:
    """Hand the list to the test archivist as the record manager; OAB's answer."""
    final = {"user": user_pk(oab, api, "archivist"), "comment": "podiumd-tests"}
    return oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/make_final/", json=final)


def review(oab: Sessions, api: str, role: str, lijst: str, **fields: object) -> JsonObject:
    """Review the list as the role's test user; the review."""
    body = {"destructionList": lijst, "listFeedback": "podiumd-tests", **fields}
    return expect_status(oab(role).post(f"{api}/destruction-list-reviews/", json=body), HTTPStatus.CREATED).json()


def ready_to_delete(oab: Sessions, api: str, zaak: JsonObject, registry: ResourceRegistry) -> str:
    """Create a list of the zaak that the reviewer and the archivist accepted; its uuid."""
    lijst = new_list(oab, api, zaak, registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    expect_status(make_final(oab, api, lijst), HTTPStatus.CREATED, HTTPStatus.OK)
    review(oab, api, "archivist", lijst, decision="accepted")
    return lijst


def queue(oab: Sessions, api: str, lijst: str) -> JsonObject:
    """Start the destruction as the record manager; the list afterwards."""
    expect_status(
        oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/queue_destruction/", json={}),
        HTTPStatus.OK,
        HTTPStatus.NO_CONTENT,
    )
    return expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()


def run_destruction(env: Environment, oab: Sessions, api: str, lijst: str) -> str:
    """Queue the list and destroy it now; its processingStatus once OAB has finished (succeeded, failed)."""
    queue(oab, api, lijst)
    destroy_now(env, lijst)

    def processed() -> str | None:
        found = expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()
        return None if found["processingStatus"] in {"new", "queued", "processing"} else str(found["processingStatus"])

    return wait_until(processed, timeout=120, description=f"destruction of list {lijst}")
