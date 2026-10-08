"""Open Archiefbeheer: roles, and a vernietigingslijst of the test's own zaak through its reviews.

Ported from TA interaction 142 and 168, regression 143, 166, 169, 170 and 171. Lists never
select all zaken: each holds only the test's own closed zaak, which the test puts in OAB's
cache. The destruction and the short procedure change OAB's global ArchiveConfig, so those
tests are destructive (tier chaos) and run on one worker.
"""

from __future__ import annotations

import secrets

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.bootstrap.names import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.steps import OAB_ROLES
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.oab import API
from podiumd_tests.oab import cache_zaken
from podiumd_tests.oab import destroy_now
from podiumd_tests.oab import login
from podiumd_tests.oab import set_archive_config
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import close_zaak
from podiumd_tests.seed.openzaak import delete_documents_of
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

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
    """A zaak of the test that ended two days ago with archiefnominatie vernietigen, in OAB's zaken cache.

    Its archiefactiedatum is yesterday, not ten years ahead: queue_destruction accepts it.
    """
    if not parts.resultaattypen:
        pytest.skip("test zaaktype has no resultaattype (Selectielijst API was unreachable at bootstrap)")
    gezet = datetime.now(UTC) - timedelta(days=2)
    zaak = close_zaak(openzaak, make_zaak(openzaak, registry, parts.zaaktype), parts, gezet)
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    zaak = openzaak.request("PATCH", str(zaak["url"]), HTTPStatus.OK, json={"archiefactiedatum": yesterday}).json()
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
        # OAB requires unique names, and the run tag is shared by all workers.
        "name": registry.tagged(f"vernietigingslijst-{secrets.token_hex(3)}"),
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


def make_final(oab: Callable[[str], requests.Session], api: str, lijst: str) -> requests.Response:
    """The record manager hands the list to the test archivist."""
    final = {"user": user_pk(oab, api, "archivist"), "comment": "podiumd-tests"}
    return oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/make_final/", json=final)


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
    expect_status(make_final(oab, api, lijst), HTTPStatus.CREATED, HTTPStatus.OK)
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
    expect_status(
        make_final(oab, api, lijst),
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.CONFLICT,
    )


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


def ready_to_delete(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> str:
    """A list of the test's zaak that reviewer and archivist accepted; its uuid."""
    lijst = new_list(oab, api, zaak, registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    expect_status(make_final(oab, api, lijst), HTTPStatus.CREATED, HTTPStatus.OK)
    review(oab, api, "archivist", lijst, decision="accepted")
    return lijst


def queue(oab: Callable[[str], requests.Session], api: str, lijst: str) -> JsonObject:
    """The record manager starts the destruction; the list afterwards."""
    expect_status(
        oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/queue_destruction/", json={}),
        HTTPStatus.OK,
        HTTPStatus.NO_CONTENT,
    )
    return expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()


def test_destruction_waits_and_can_be_aborted(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """Started destruction is planned after the waiting period, and aborting returns the list (TA reg-170 ABC-034)."""
    lijst = ready_to_delete(oab, api, zaak, registry)
    planned = queue(oab, api, lijst).get("plannedDestructionDate")
    assert planned
    assert str(planned) > today()
    abort = {"comment": "podiumd-tests"}
    expect_status(oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/abort/", json=abort), HTTPStatus.OK)
    assert status(oab, api, lijst) == "new"


@pytest.fixture(name="archive_config")
def fixture_archive_config(podiumd_env: Environment) -> Iterator[Callable[..., None]]:
    """set(**fields): change OAB's global ArchiveConfig for this test; the old values come back after it."""
    old: dict[str, object] = {}

    def set_fields(**fields: object) -> None:
        for field, value in set_archive_config(podiumd_env, fields).items():
            old.setdefault(field, value)

    yield set_fields
    if old:
        set_archive_config(podiumd_env, old)


@pytest.mark.destructive
@pytest.mark.xfail(
    strict=True,
    reason="Open Zaak 1.29.3 answers 500 on DELETE of a zaak with a resultaat although it deletes it"
    " (test_closed_zaak_delete_answers_204); Open Archiefbeheer marks the item failed, so the list"
    " never reaches deleted and files no report; not yet reported upstream",
)
def test_destruction_deletes_the_zaak_and_leaves_a_report(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    oab: Callable[[str], requests.Session],
    api: str,
    openzaak: ApiClient,
    zaak: JsonObject,
    parts: ZaaktypeParts,
    registry: ResourceRegistry,
    archive_config: Callable[..., None],
) -> None:
    """The destruction deletes the zaak in Open Zaak and files a report the record manager downloads (TA reg-170).

    The report goes to a zaak of the test zaaktype; the waiting period is skipped for this list only.
    """
    archive_config(
        bronorganisatie=TEST_CATALOGUS_RSIN,
        zaaktype=parts.zaaktype,
        statustype=str(parts.statustypen[-1]["url"]),
        resultaattype=parts.resultaattypen[0],
        informatieobjecttype=parts.informatieobjecttype,
    )
    lijst = ready_to_delete(oab, api, zaak, registry)
    naam = str(
        expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()["name"]
    )

    def delete_report() -> None:
        for rapport in openzaak.list(f"{ZAKEN}/zaken", {"zaaktype": parts.zaaktype}):
            if naam in str(rapport.get("toelichting") or ""):
                delete_documents_of(openzaak, str(rapport["url"]))
                delete_zaak(openzaak, str(rapport["url"]))

    registry.add(f"destruction report of {naam}", delete_report)
    queue(oab, api, lijst)
    destroy_now(podiumd_env, lijst)

    def processed() -> str | None:
        found = expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()
        return None if found["processingStatus"] in {"new", "queued", "processing"} else str(found["processingStatus"])

    assert wait_until(processed, timeout=120, description=f"destruction of list {lijst}") == "succeeded"
    assert status(oab, api, lijst) == "deleted"
    openzaak.request("GET", str(zaak["url"]), HTTPStatus.NOT_FOUND)
    report = oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/download_report/")
    assert expect_status(report, HTTPStatus.OK).content


@pytest.mark.destructive
def test_short_procedure_skips_the_archivist(
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    archive_config: Callable[..., None],
) -> None:
    """For a zaaktype with the short procedure, the reviewer's acceptance makes the list ready to delete (TA reg-171)."""
    archive_config(zaaktypes_short_process=[TEST_ZAAKTYPE])
    lijst = new_list(oab, api, zaak, registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    assert status(oab, api, lijst) == "ready_to_delete"
