"""Open Archiefbeheer: roles, and a vernietigingslijst of the test's own zaak through its reviews.

Ported from TA interaction 142 and 168, regression 143, 166 and 169. Lists never select all
zaken: each holds only the test's own closed zaak, which the test puts in OAB's cache. The
list stops at ready_to_delete; queue_destruction (TA 170) would delete zaken in Open Zaak.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import OAB_ROLES
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.oab import API
from podiumd_tests.oab import cache_zaken
from podiumd_tests.oab import login
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import close_zaak
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.cluster,
    pytest.mark.requires("openarchiefbeheer", "openzaak", "cluster"),
]

# What each role may do (whoami role flags).
PERMISSIONS = {
    "recordmanager": {"canStartDestruction": True, "canReviewDestruction": False},
    "reviewer": {"canStartDestruction": False, "canReviewDestruction": True},
    "coreviewer": {"canStartDestruction": False, "canCoReviewDestruction": True},
    "archivist": {"canStartDestruction": False, "canReviewFinalList": True},
}


@pytest.fixture(name="oab")
def fixture_oab(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> Callable[[str], requests.Session]:
    """A logged-in session per role, made once per test."""
    sessions: dict[str, requests.Session] = {}

    def session(role: str) -> requests.Session:
        if role not in sessions:
            need_bootstrap(f"openarchiefbeheer-user-{role}")
            sessions[role] = login(podiumd_env, role)
        return sessions[role]

    return session


@pytest.fixture(name="api")
def fixture_api(urls: dict[str, str]) -> str:
    """OAB's API root."""
    return urls["openarchiefbeheer"] + API


@pytest.fixture(name="zaak")
def fixture_zaak(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> JsonObject:
    """A zaak of the test that ended two days ago with archiefnominatie vernietigen, in OAB's zaken cache."""
    if not parts.resultaattypen:
        pytest.skip("test zaaktype has no resultaattype (Selectielijst API was unreachable at bootstrap)")
    gezet = datetime.now(UTC) - timedelta(days=2)
    zaak = close_zaak(openzaak, make_zaak(openzaak, registry, parts.zaaktype), parts, gezet)
    url = str(zaak["url"])
    registry.add(f"OAB cache of {url}", lambda: cache_zaken(podiumd_env, [url], cached=False))
    cache_zaken(podiumd_env, [url], cached=True)
    return zaak


def user_pk(oab: Callable[[str], requests.Session], api: str, role: str) -> int:
    """The pk of the role's test user, as OAB lists users per assignee role."""
    filter_role = {"reviewer": "main_reviewer", "coreviewer": "co_reviewer"}.get(role, role)
    users = expect_status(oab("recordmanager").get(api + "/users/", params={"role": filter_role}), HTTPStatus.OK)
    return next(int(str(u["pk"])) for u in entries(users.json()) if str(u["username"]).endswith(f"-{role}"))


def status(oab: Callable[[str], requests.Session], api: str, lijst: str) -> str:
    """The list's status, as the record manager sees it."""
    return str(
        expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()["status"]
    )


def new_list(oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry) -> str:
    """A vernietigingslijst with only the test's zaak and the test reviewer, made ready to review; its uuid."""
    body = {
        "name": registry.tagged("vernietigingslijst"),
        "comment": "podiumd-tests",
        "containsSensitiveInfo": False,
        "add": [{"zaak": zaak["url"]}],
        "reviewer": {"user": user_pk(oab, api, "reviewer")},
    }
    created = expect_status(
        oab("recordmanager").post(api + "/destruction-lists/", json=body), HTTPStatus.CREATED
    ).json()
    lijst = str(created["uuid"])
    expect_status(
        oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/mark_ready_review/", json={}),
        HTTPStatus.CREATED,
        HTTPStatus.OK,
    )
    return lijst


def review(oab: Callable[[str], requests.Session], api: str, role: str, lijst: str, **fields: object) -> JsonObject:
    """A review of the list by the role's test user."""
    body = {"destructionList": lijst, "listFeedback": "podiumd-tests", **fields}
    return expect_status(oab(role).post(api + "/destruction-list-reviews/", json=body), HTTPStatus.CREATED).json()


def test_anonymous_lists_are_refused(http: requests.Session, api: str) -> None:
    """Without a session the vernietigingslijsten are refused (TA int-142)."""
    expect_status(http.get(api + "/destruction-lists/"), *REFUSED)


@pytest.mark.parametrize("role", sorted(OAB_ROLES))
def test_role_permissions(oab: Callable[[str], requests.Session], api: str, role: str) -> None:
    """Each role's test user has exactly its role's permissions (TA int-142, reg-143 ABC-006/012, reg-166 ABC-036/037)."""
    me = expect_status(oab(role).get(api + "/whoami/"), HTTPStatus.OK).json()
    assert {k: section(me, "role").get(k) for k in PERMISSIONS[role]} == PERMISSIONS[role]


@pytest.mark.core
def test_list_goes_through_both_reviews(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """Reviewer and archivist accept the list of the test's zaak, which then waits for destruction (TA 142, 143, 168)."""
    lijst = new_list(oab, api, zaak, registry)
    items = oab("recordmanager").get(api + "/destruction-list-items/", params={"item-destruction_list": lijst})
    body = expect_status(items, HTTPStatus.OK).json()
    rows = entries(body.get("results") if isinstance(body, dict) else body)
    assert [section(i, "zaak").get("url") for i in rows] == [zaak["url"]]
    review(oab, api, "reviewer", lijst, decision="accepted")
    assert status(oab, api, lijst) == "internally_reviewed"
    final = {"user": user_pk(oab, api, "archivist"), "comment": "podiumd-tests"}
    expect_status(
        oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/make_final/", json=final),
        HTTPStatus.CREATED,
        HTTPStatus.OK,
    )
    assert status(oab, api, lijst) == "ready_for_archivist"
    review(oab, api, "archivist", lijst, decision="accepted")
    assert status(oab, api, lijst) == "ready_to_delete"


def test_rejected_list_goes_back_to_the_record_manager(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """A rejection asks the record manager for changes, and such a list cannot be made final (TA 143 ABC-009, 169)."""
    lijst = new_list(oab, api, zaak, registry)
    review(
        oab, api, "reviewer", lijst, decision="rejected", zakenReviews=[{"zaakUrl": zaak["url"], "feedback": "bewaren"}]
    )
    assert status(oab, api, lijst) == "changes_requested"
    final = {"user": user_pk(oab, api, "archivist"), "comment": "podiumd-tests"}
    refused = oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/make_final/", json=final)
    expect_status(refused, HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT)


def test_coreviewer_feedback_reaches_the_reviewer(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """A co-reviewer added to the list gives feedback that the reviewer sees (TA reg-166 ABC-038..041)."""
    lijst = new_list(oab, api, zaak, registry)
    add = {"comment": "podiumd-tests", "add": [{"user": user_pk(oab, api, "coreviewer")}]}
    expect_status(
        oab("recordmanager").put(f"{api}/destruction-lists/{lijst}/co-reviewers/", json=add),
        HTTPStatus.OK,
        HTTPStatus.CREATED,
        HTTPStatus.NO_CONTENT,
    )
    feedback = registry.tagged("medebeoordeling")
    co_review = {"destructionList": lijst, "listFeedback": feedback}
    expect_status(oab("coreviewer").post(api + "/destruction-list-co-reviews/", json=co_review), HTTPStatus.CREATED)
    seen = oab("reviewer").get(api + "/destruction-list-co-reviews/", params={"destruction_list__uuid": lijst})
    assert feedback in [str(r.get("listFeedback")) for r in entries(expect_status(seen, HTTPStatus.OK).json())]
