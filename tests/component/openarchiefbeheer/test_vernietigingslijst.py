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

from playwright.sync_api import expect

from podiumd_tests.bootstrap.names import PREFIX
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
from podiumd_tests.oab import ui_login
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import close_zaak
from podiumd_tests.seed.openzaak import delete_documents_of
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    import requests

    from playwright.sync_api import Page

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


# Only the timeout of a list stuck after a response is excused; any other failure still fails.
RESPONSE_RACE = pytest.mark.xfail(
    strict=False,
    raises=WaitTimeoutError,
    reason="Open Archiefbeheer 2.0.0 queues process_review_response inside the request's transaction"
    " (destruction/api/serializers.py: .delay without on_commit); a quick worker finds no ReviewResponse"
    " (DoesNotExist) and the list stays changes_requested; not yet reported",
)
REVIEWER_RENAMES = pytest.mark.xfail(
    strict=True,
    reason="Open Archiefbeheer: the reviewer, while the list is assigned to it, can rename (PATCH) the list;"
    " the draaiboek leaves changes to the record manager; not yet reported",
)


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


@pytest.fixture(name="closed_zaak")
def fixture_closed_zaak(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> Callable[[], JsonObject]:
    """Makes a zaak of the test that ended two days ago with archiefnominatie vernietigen, in OAB's zaken cache.

    Its archiefactiedatum is yesterday, not ten years ahead: queue_destruction accepts it.
    """
    if not parts.resultaattypen:
        pytest.skip("test zaaktype has no resultaattype (Selectielijst API was unreachable at bootstrap)")
    return lambda: _closed_zaak(podiumd_env, openzaak, registry, parts)


@pytest.fixture(name="zaak")
def fixture_zaak(closed_zaak: Callable[[], JsonObject]) -> JsonObject:
    """One closed zaak of the test, in OAB's zaken cache."""
    return closed_zaak()


def _closed_zaak(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> JsonObject:
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


def rows(response: requests.Response) -> list[JsonObject]:
    """The objects of an OAB list answer (200), paginated or not."""
    body = expect_status(response, HTTPStatus.OK).json()
    return entries(body.get("results") if isinstance(body, dict) else body)


def zaken_on(oab: Callable[[str], requests.Session], api: str, lijst: str) -> list[object]:
    """The URLs of the zaken on the list; a zaak taken off keeps its item, with status removed."""
    params = {"item-destruction_list": lijst, "item-status": "suggested"}
    items = oab("recordmanager").get(api + "/destruction-list-items/", params=params)
    return [section(i, "zaak").get("url") for i in rows(items)]


def status(oab: Callable[[str], requests.Session], api: str, lijst: str) -> str:
    """The list's status, as the record manager sees it."""
    return str(
        expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()["status"]
    )


def new_list(
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject | list[JsonObject],
    registry: ResourceRegistry,
    *,
    ready: bool = True,
) -> str:
    """A vernietigingslijst with only the test's zaak (or zaken) and the test reviewer, by default made ready to review."""
    zaken = zaak if isinstance(zaak, list) else [zaak]
    body = {
        # OAB requires unique names, and the run tag is shared by all workers.
        "name": registry.tagged(f"vernietigingslijst-{secrets.token_hex(3)}"),
        "comment": "podiumd-tests",
        "containsSensitiveInfo": False,
        "add": [{"zaak": z["url"]} for z in zaken],
        "reviewer": {"user": user_pk(oab, api, "reviewer")},
    }
    created = expect_status(
        oab("recordmanager").post(api + "/destruction-lists/", json=body), HTTPStatus.CREATED
    ).json()
    lijst = str(created["uuid"])
    if ready:
        expect_status(
            oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/mark_ready_review/", json={}),
            HTTPStatus.CREATED,
            HTTPStatus.OK,
        )
    return lijst


def reject(oab: Callable[[str], requests.Session], api: str, role: str, lijst: str, zaken: list[JsonObject]) -> int:
    """The role's test user rejects the list, proposing to keep these zaken; the review's pk."""
    proposals = [{"zaakUrl": z["url"], "feedback": "bewaren"} for z in zaken]
    return int(str(review(oab, api, role, lijst, decision="rejected", zakenReviews=proposals)["pk"]))


# The record manager's answers to a proposal: decline it, or take it over (OAB then changes the zaak).
KEEP: dict[str, object] = {"actionItem": "keep"}
TAKE_OVER: dict[str, object] = {
    "actionItem": "remove",
    "actionZaakType": "bewaartermijn",
    "actionZaak": {"archiefactiedatum": (datetime.now(UTC) + timedelta(days=3650)).date().isoformat()},
}


def respond(
    oab: Callable[[str], requests.Session], api: str, review_pk: int, actions: dict[str, dict[str, object]]
) -> None:
    """The record manager answers the review's items: zaak URL -> KEEP or TAKE_OVER."""
    items = rows(oab("recordmanager").get(api + "/review-items/", params={"item-review-review": str(review_pk)}))
    zaak_of = {item["pk"]: section(section(item, "destructionListItem"), "zaak").get("url") for item in items}
    responses = [{"reviewItem": pk, **actions[str(url)]} for pk, url in zaak_of.items()]
    body = {"review": review_pk, "comment": "podiumd-tests", "itemsResponses": responses}
    expect_status(oab("recordmanager").post(api + "/review-responses/", json=body), HTTPStatus.CREATED)


def wait_for_status(oab: Callable[[str], requests.Session], api: str, lijst: str, wanted: str) -> None:
    """Wait until the list has the status; OAB processes review responses in a background task."""
    wait_until(lambda: status(oab, api, lijst) == wanted, timeout=60, description=f"list {lijst} {wanted}")


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
@pytest.mark.tc("ABC-008", "ABC-018", "ABC-023")
def test_list_goes_through_both_reviews(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """Reviewer and archivist accept the list of the test's zaak, which then waits for destruction (TA 142, 143, 168)."""
    lijst = new_list(oab, api, zaak, registry)
    assert zaken_on(oab, api, lijst) == [zaak["url"]]
    review(oab, api, "reviewer", lijst, decision="accepted")
    assert status(oab, api, lijst) == "internally_reviewed"
    expect_status(make_final(oab, api, lijst), HTTPStatus.CREATED, HTTPStatus.OK)
    assert status(oab, api, lijst) == "ready_for_archivist"
    review(oab, api, "archivist", lijst, decision="accepted")
    assert status(oab, api, lijst) == "ready_to_delete"


@pytest.mark.tc("ABC-009", "ABC-016")
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


@RESPONSE_RACE
@pytest.mark.tc("ABC-015")
def test_record_manager_response_sends_the_list_back_to_review(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """The record manager declines the reviewer's proposal: the list goes back to the reviewer unchanged (TA 168, 169)."""
    lijst = new_list(oab, api, zaak, registry)
    respond(oab, api, reject(oab, api, "reviewer", lijst, [zaak]), {str(zaak["url"]): KEEP})
    wait_for_status(oab, api, lijst, "ready_to_review")
    assert zaken_on(oab, api, lijst) == [zaak["url"]]


@RESPONSE_RACE
@pytest.mark.tc("ABC-013")
def test_record_manager_takes_the_proposals_over(
    oab: Callable[[str], requests.Session], api: str, closed_zaak: Callable[[], JsonObject], registry: ResourceRegistry
) -> None:
    """The record manager agrees to the reviewer's proposal: that zaak leaves the list, which goes back to review."""
    kept, stays = closed_zaak(), closed_zaak()
    lijst = new_list(oab, api, [kept, stays], registry)
    respond(oab, api, reject(oab, api, "reviewer", lijst, [kept]), {str(kept["url"]): TAKE_OVER})
    wait_for_status(oab, api, lijst, "ready_to_review")
    assert zaken_on(oab, api, lijst) == [stays["url"]]


@pytest.mark.tc("ABC-012")
@pytest.mark.xfail(
    strict=True,
    reason="Open Archiefbeheer: a review response cannot empty the archiefactiedatum ('Dit veld mag niet leeg"
    " zijn'), so a proposal to keep a zaak forever cannot be taken over as the draaiboek asks; not yet reported",
)
def test_keeping_forever_empties_the_archiefactiedatum(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    oab: Callable[[str], requests.Session],
    api: str,
    closed_zaak: Callable[[], JsonObject],
    openzaak: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """Agreeing to keep a zaak forever leaves its archiefactiedatum empty in Open Zaak."""
    forever, stays = closed_zaak(), closed_zaak()
    lijst = new_list(oab, api, [forever, stays], registry)
    forever_action = {**TAKE_OVER, "actionZaak": {"archiefactiedatum": None}}
    respond(oab, api, reject(oab, api, "reviewer", lijst, [forever]), {str(forever["url"]): forever_action})
    wait_for_status(oab, api, lijst, "ready_to_review")
    assert openzaak.get(str(forever["url"])).get("archiefactiedatum") is None


@RESPONSE_RACE
@pytest.mark.tc("ABC-019", "ABC-022")
def test_archivist_rejection_goes_back_and_returns_to_the_archivist(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """The archivist's rejection goes back to the record manager; declined, the list returns to the archivist unchanged."""
    lijst = new_list(oab, api, zaak, registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    expect_status(make_final(oab, api, lijst), HTTPStatus.CREATED, HTTPStatus.OK)
    rejection = reject(oab, api, "archivist", lijst, [zaak])
    assert status(oab, api, lijst) == "changes_requested"
    respond(oab, api, rejection, {str(zaak["url"]): KEEP})
    wait_for_status(oab, api, lijst, "ready_for_archivist")
    assert zaken_on(oab, api, lijst) == [zaak["url"]]


@RESPONSE_RACE
@pytest.mark.tc("ABC-020", "ABC-021")
def test_record_manager_takes_some_archivist_proposals_over(
    oab: Callable[[str], requests.Session], api: str, closed_zaak: Callable[[], JsonObject], registry: ResourceRegistry
) -> None:
    """Agreeing to one of the archivist's two proposals: that zaak leaves, the list returns to the archivist."""
    taken, declined, stays = closed_zaak(), closed_zaak(), closed_zaak()
    lijst = new_list(oab, api, [taken, declined, stays], registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    expect_status(make_final(oab, api, lijst), HTTPStatus.CREATED, HTTPStatus.OK)
    rejection = reject(oab, api, "archivist", lijst, [taken, declined])
    respond(oab, api, rejection, {str(taken["url"]): TAKE_OVER, str(declined["url"]): KEEP})
    wait_for_status(oab, api, lijst, "ready_for_archivist")
    assert sorted(map(str, zaken_on(oab, api, lijst))) == sorted([str(declined["url"]), str(stays["url"])])


@pytest.mark.tc("ABC-004")
def test_record_manager_adds_zaken_before_review(
    oab: Callable[[str], requests.Session], api: str, closed_zaak: Callable[[], JsonObject], registry: ResourceRegistry
) -> None:
    """A list not yet offered for review takes more zaken."""
    first, second = closed_zaak(), closed_zaak()
    lijst = new_list(oab, api, first, registry, ready=False)
    added = oab("recordmanager").patch(f"{api}/destruction-lists/{lijst}/", json={"add": [{"zaak": second["url"]}]})
    expect_status(added, HTTPStatus.OK)
    assert sorted(map(str, zaken_on(oab, api, lijst))) == sorted([str(first["url"]), str(second["url"])])


@pytest.mark.tc("ABC-006", "ABC-017", "ABC-026")
@pytest.mark.parametrize("role", [pytest.param("reviewer", marks=REVIEWER_RENAMES), "archivist", "coreviewer"])
def test_only_the_record_manager_changes_the_list(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry, role: str
) -> None:
    """Reviewers, co-reviewers and the archivist cannot rename the list; that is the record manager's work.

    OAB answers 404 to a user who may not see the list, 403 to one who may see it.
    """
    lijst = new_list(oab, api, zaak, registry)
    changed = oab(role).patch(f"{api}/destruction-lists/{lijst}/", json={"name": registry.tagged("hernoemd")})
    expect_status(changed, *REFUSED, HTTPStatus.NOT_FOUND)


@pytest.mark.tc("ABC-031")
def test_reviewer_forwards_without_the_coreviewer(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """With a co-reviewer assigned who has not reacted, the reviewer can still accept the list."""
    lijst = new_list(oab, api, zaak, registry)
    assign_coreviewer(oab, api, lijst)
    review(oab, api, "reviewer", lijst, decision="accepted")
    assert status(oab, api, lijst) == "internally_reviewed"


@pytest.mark.ui
@pytest.mark.tc("ABC-002")
def test_record_manager_creates_a_list_in_the_ui(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """The record manager selects the test's zaak in the UI and makes a list of it, which opens for editing (TA 143 ABC-001-003)."""
    oab("recordmanager")  # bootstraps the test user
    naam = registry.tagged(f"ui-lijst-{secrets.token_hex(3)}")
    ui_login(page, podiumd_env, "recordmanager")
    identificatie = str(zaak["identificatie"])
    page.goto(
        f"{podiumd_env.profile.urls['openarchiefbeheer']}/destruction-lists/create?identificatie__icontains={identificatie}"
    )
    page.get_by_role("row", name=identificatie).get_by_role("checkbox").check()
    page.get_by_role("button", name="Vernietigingslijst opstellen").last.click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Naam").fill(naam)
    dialog.get_by_role("combobox", name="Reviewer").click()
    # The options are a listbox without option roles.
    dialog.get_by_role("listbox").get_by_text(f"{PREFIX}-reviewer", exact=True).click()
    dialog.get_by_label("Toelichting").fill("podiumd-tests")
    dialog.get_by_role("button", name="Vernietigingslijst opstellen").click()
    expect(page.get_by_text(naam)).to_be_visible()
    lijsten = rows(oab("recordmanager").get(api + "/destruction-lists/", params={"name": naam}))
    lijst = next(str(found["uuid"]) for found in lijsten if found.get("name") == naam)
    assert zaken_on(oab, api, lijst) == [zaak["url"]]
    page.get_by_text(naam).click()
    expect(page.get_by_role("heading", name=naam)).to_be_visible()
    expect(page.get_by_text(identificatie).first).to_be_visible()


@pytest.mark.ui
@pytest.mark.tc("ABC-009", "ABC-010")
def test_record_manager_sees_the_proposals_in_the_ui(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    page: Page,
    podiumd_env: Environment,
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """After a rejection, the list's page shows the record manager the reviewer's proposal for the zaak (TA 143 ABC-011)."""
    lijst = new_list(oab, api, zaak, registry)
    feedback = registry.tagged("voorstel")
    review(
        oab, api, "reviewer", lijst, decision="rejected", zakenReviews=[{"zaakUrl": zaak["url"], "feedback": feedback}]
    )
    ui_login(page, podiumd_env, "recordmanager")
    page.goto(f"{podiumd_env.profile.urls['openarchiefbeheer']}/destruction-lists/{lijst}")
    expect(page.get_by_text(str(zaak["identificatie"])).first).to_be_visible()
    expect(page.get_by_text(feedback).first).to_be_visible()


@pytest.mark.tc("ABC-025", "ABC-027", "ABC-028", "ABC-030")
@pytest.mark.ui
@pytest.mark.tc("ABC-005")
def test_reviewer_finds_the_assigned_list_in_the_ui(
    page: Page,
    podiumd_env: Environment,
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """The reviewer the list is assigned to sees it after logging in on OAB's own site."""
    lijst = new_list(oab, api, zaak, registry)
    naam = str(
        expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()["name"]
    )
    ui_login(page, podiumd_env, "reviewer")
    expect(page.get_by_text(naam)).to_be_visible()


def assign_coreviewer(oab: Callable[[str], requests.Session], api: str, lijst: str) -> None:
    """The record manager adds the test co-reviewer to the list."""
    add = {"comment": "podiumd-tests", "add": [{"user": user_pk(oab, api, "coreviewer")}]}
    put = oab("recordmanager").put(f"{api}/destruction-lists/{lijst}/co-reviewers/", json=add)
    expect_status(put, HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.NO_CONTENT)


def test_coreviewer_feedback_reaches_the_reviewer(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """A co-reviewer added to the list gives feedback that the reviewer sees (TA reg-166 ABC-038..041)."""
    lijst = new_list(oab, api, zaak, registry)
    assign_coreviewer(oab, api, lijst)
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


@pytest.mark.tc("ABC-024")
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
@pytest.mark.tc("ABC-032")
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
@pytest.mark.tc("ABC-038")
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
