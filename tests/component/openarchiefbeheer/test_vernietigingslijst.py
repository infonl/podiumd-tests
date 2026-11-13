"""Open Archiefbeheer: roles, and a vernietigingslijst of the test's own zaak through its reviews.

Ported from TA interaction 142 and 168, regression 143, 166 and 169. Lists never
select all zaken: each holds only the test's own closed zaak, which the test puts in OAB's
cache. The destruction tests are in test_vernietiging.py.
"""

from __future__ import annotations

import secrets
import warnings

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.steps import OAB_ROLES
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.oab import forget_zaken
from podiumd_tests.oab import is_review_queued_after_commit
from podiumd_tests.oab import list_status
from podiumd_tests.oab import make_final
from podiumd_tests.oab import new_list
from podiumd_tests.oab import process_review_response
from podiumd_tests.oab import review
from podiumd_tests.oab import ui_login
from podiumd_tests.oab import user_pk
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.cluster,
    pytest.mark.requires("openarchiefbeheer", "openzaak", "cluster"),
]

INT_142 = pytest.mark.source(
    "TA interaction/142-oab-vernietigingslijst.spec.ts",
    "OAB's vernietigingslijst flow: the API enforces auth, a list is made and a reviewer accepts it.",
)
INT_168 = pytest.mark.source(
    "TA interaction/168-oab-archivist-flow.spec.ts",
    "OAB's archivist review: the archivist accepts the list or rejects it back to the record manager.",
)
REG_143 = pytest.mark.source(
    "TA regression/143-oab-vernietigingsflow.spec.ts",
    "OAB's full vernietigingslijst flow of draaiboek cases ABC-001 to ABC-012.",
)
REG_166 = pytest.mark.source(
    "TA regression/166-oab-medebeoordelaar.spec.ts",
    "OAB's co-reviewer: opens the list, cannot change it, and gives feedback that reaches the reviewer.",
)
REG_169 = pytest.mark.source(
    "TA regression/169-oab-process-review-flow.spec.ts",
    "OAB's record manager handles a reviewer's rejection: agrees with all, some or none of the proposals.",
)


# What each role may do (whoami role flags).
PERMISSIONS = {
    "recordmanager": {"canStartDestruction": True, "canReviewDestruction": False},
    "reviewer": {"canStartDestruction": False, "canReviewDestruction": True},
    "coreviewer": {"canStartDestruction": False, "canCoReviewDestruction": True},
    "archivist": {"canStartDestruction": False, "canReviewFinalList": True},
    "beheerder": {"canConfigureApplication": True},
}


REVIEWER_RENAMES = pytest.mark.xfail(
    strict=True,
    reason="[open-archiefbeheer-2] Open Archiefbeheer: the reviewer, while the list is assigned to it, can rename (PATCH) the list;"
    " the draaiboek leaves changes to the record manager; not yet reported",
)


def rows(response: requests.Response) -> list[JsonObject]:
    """The objects of an OAB list answer (200), paginated or not."""
    body = expect_status(response, HTTPStatus.OK).json()
    return entries(body.get("results") if isinstance(body, dict) else body)


def zaken_on(oab: Callable[[str], requests.Session], api: str, lijst: str) -> list[object]:
    """The URLs of the zaken on the list; a zaak taken off keeps its item, with status removed."""
    params = {"item-destruction_list": lijst, "item-status": "suggested"}
    items = oab("recordmanager").get(f"{api}/destruction-list-items/", params=params)
    return [section(i, "zaak").get("url") for i in rows(items)]


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
    oab: Callable[[str], requests.Session],
    api: str,
    env: Environment,
    lijst: str,
    review_pk: int,
    actions: dict[str, dict[str, object]],
    wanted: str,
) -> None:
    """The record manager answers the review's items (zaak URL -> KEEP or TAKE_OVER); the list then gets status wanted.

    OAB processes the response in a background task. When the worker dropped it ([open-archiefbeheer-1]), the test
    processes it and warns, so the flow is still checked.
    """
    items = rows(oab("recordmanager").get(f"{api}/review-items/", params={"item-review-review": str(review_pk)}))
    zaak_of = {item["pk"]: section(section(item, "destructionListItem"), "zaak").get("url") for item in items}
    responses = [{"reviewItem": pk, **actions[str(url)]} for pk, url in zaak_of.items()]
    body = {"review": review_pk, "comment": "podiumd-tests", "itemsResponses": responses}
    expect_status(oab("recordmanager").post(f"{api}/review-responses/", json=body), HTTPStatus.CREATED)
    try:
        wait_until(lambda: list_status(oab, api, lijst) == wanted, timeout=60, description=f"list {lijst} {wanted}")
    except WaitTimeoutError:
        if not process_review_response(env, lijst):
            raise
        warnings.warn(
            f"[open-archiefbeheer-1] list {lijst}: the test processed the dropped review response", stacklevel=2
        )
        assert list_status(oab, api, lijst) == wanted


@INT_142
@pytest.mark.scenario("""
    When a visitor without a session asks Open Archiefbeheer for the vernietigingslijsten
    Then Open Archiefbeheer refuses the request
""")
def test_anonymous_lists_are_refused(http: requests.Session, api: str) -> None:
    """Without a session the vernietigingslijsten are refused (TA int-142)."""
    expect_status(http.get(f"{api}/destruction-lists/"), *REFUSED)


@pytest.mark.parametrize("role", sorted(OAB_ROLES))
@INT_142
@REG_143
@REG_166
@pytest.mark.scenario("""
    Given a test user with one Open Archiefbeheer role
    When the user asks Open Archiefbeheer for their own account
    Then Open Archiefbeheer gives the user exactly the permissions of that role
""")
def test_role_permissions(oab: Callable[[str], requests.Session], api: str, role: str) -> None:
    """Each role's test user has exactly its role's permissions (TA int-142, reg-143 ABC-006/012, reg-166 ABC-036/037)."""
    me = expect_status(oab(role).get(f"{api}/whoami/"), HTTPStatus.OK).json()
    assert {k: section(me, "role").get(k) for k in PERMISSIONS[role]} == PERMISSIONS[role]


@pytest.mark.core
@pytest.mark.tc("ABC-008", "ABC-018", "ABC-023")
@INT_142
@REG_143
@INT_168
@pytest.mark.scenario("""
    Given the record manager made a vernietigingslijst of one closed zaak
    Then the list holds only that zaak
    When the reviewer accepts the list
    Then the list is internally reviewed
    When the record manager hands it to the archivist and the archivist accepts it
    Then the list is ready to delete
""")
def test_list_goes_through_both_reviews(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """Reviewer and archivist accept the list of the test's zaak, which then waits for destruction (TA 142, 143, 168)."""
    lijst = new_list(oab, api, zaak, registry)
    assert zaken_on(oab, api, lijst) == [zaak["url"]]
    review(oab, api, "reviewer", lijst, decision="accepted")
    assert list_status(oab, api, lijst) == "internally_reviewed"
    expect_status(make_final(oab, api, lijst), HTTPStatus.CREATED, HTTPStatus.OK)
    assert list_status(oab, api, lijst) == "ready_for_archivist"
    review(oab, api, "archivist", lijst, decision="accepted")
    assert list_status(oab, api, lijst) == "ready_to_delete"


@pytest.mark.tc("ABC-009", "ABC-016")
@REG_143
@REG_169
@pytest.mark.scenario("""
    Given a vernietigingslijst of one closed zaak, ready for review
    When the reviewer rejects it, proposing to keep the zaak
    Then the list asks the record manager for changes
    And the record manager cannot hand it to the archivist
""")
def test_rejected_list_goes_back_to_the_record_manager(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """A rejection asks the record manager for changes, and such a list cannot be made final (TA 143 ABC-009, 169)."""
    lijst = new_list(oab, api, zaak, registry)
    review(
        oab, api, "reviewer", lijst, decision="rejected", zakenReviews=[{"zaakUrl": zaak["url"], "feedback": "bewaren"}]
    )
    assert list_status(oab, api, lijst) == "changes_requested"
    expect_status(
        make_final(oab, api, lijst),
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.CONFLICT,
    )


@pytest.mark.xfail(
    strict=True,
    reason="[open-archiefbeheer-1] Open Archiefbeheer 2.0.0 queues process_review_response inside the request's transaction"
    " (destruction/api/serializers.py: .delay without on_commit); a quick worker finds no ReviewResponse (DoesNotExist)"
    " and the list stays changes_requested; open-archiefbeheer#1103",
)
@pytest.mark.source(
    "podiumd-tests", "OAB queues the review response task before its commit, so the worker can miss the response."
)
@pytest.mark.scenario("""
    Given the record manager answers a review of a vernietigingslijst
    When Open Archiefbeheer stores the answer
    Then it hands the answer to its worker only once the answer is stored
""")
def test_review_response_is_queued_after_its_commit(podiumd_env: Environment) -> None:
    """ReviewResponseSerializer.create queues its task with transaction.on_commit, so the worker finds the response."""
    assert is_review_queued_after_commit(podiumd_env)


@pytest.mark.tc("ABC-015")
@INT_168
@REG_169
@pytest.mark.scenario("""
    Given a vernietigingslijst of one closed zaak
    And the reviewer rejected it, proposing to keep the zaak
    When the record manager declines the proposal
    Then the list is ready for review again
    And the zaak is still on the list
""")
def test_record_manager_response_sends_the_list_back_to_review(
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    podiumd_env: Environment,
) -> None:
    """The record manager declines the reviewer's proposal: the list goes back to the reviewer unchanged (TA 168, 169)."""
    lijst = new_list(oab, api, zaak, registry)
    respond(
        oab,
        api,
        podiumd_env,
        lijst,
        reject(oab, api, "reviewer", lijst, [zaak]),
        {str(zaak["url"]): KEEP},
        "ready_to_review",
    )
    assert zaken_on(oab, api, lijst) == [zaak["url"]]


@pytest.mark.tc("ABC-013")
@pytest.mark.source(
    "draaiboek ABC-013",
    "The record manager can agree with all of the reviewer's proposals; the list goes back for review.",
)
@pytest.mark.scenario("""
    Given a vernietigingslijst of two closed zaken
    And the reviewer rejected it, proposing to keep one zaak
    When the record manager agrees and gives that zaak a later archiefactiedatum
    Then the list is ready for review again
    And only the other zaak is on the list
""")
def test_record_manager_takes_the_proposals_over(
    oab: Callable[[str], requests.Session],
    api: str,
    closed_zaak: Callable[[], JsonObject],
    registry: ResourceRegistry,
    podiumd_env: Environment,
) -> None:
    """The record manager agrees to the reviewer's proposal: that zaak leaves the list, which goes back to review."""
    kept, stays = closed_zaak(), closed_zaak()
    lijst = new_list(oab, api, [kept, stays], registry)
    respond(
        oab,
        api,
        podiumd_env,
        lijst,
        reject(oab, api, "reviewer", lijst, [kept]),
        {str(kept["url"]): TAKE_OVER},
        "ready_to_review",
    )
    assert zaken_on(oab, api, lijst) == [stays["url"]]


@pytest.mark.tc("ABC-012")
@pytest.mark.xfail(
    strict=True,
    reason="[open-archiefbeheer-3] Open Archiefbeheer: a review response cannot empty the archiefactiedatum ('Dit veld mag niet leeg"
    " zijn'), so a proposal to keep a zaak forever cannot be taken over as the draaiboek asks; not yet reported",
)
@pytest.mark.source(
    "draaiboek ABC-012", "A proposal to keep a zaak forever must be able to leave its archiefactiedatum empty."
)
@pytest.mark.scenario("""
    Given a vernietigingslijst of two closed zaken
    And the reviewer rejected it, proposing to keep one zaak forever
    When the record manager agrees and empties that zaak's archiefactiedatum
    Then the list is ready for review again
    And the zaak in Open Zaak has no archiefactiedatum
""")
def test_keeping_forever_empties_the_archiefactiedatum(
    oab: Callable[[str], requests.Session],
    api: str,
    closed_zaak: Callable[[], JsonObject],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    podiumd_env: Environment,
) -> None:
    """Agreeing to keep a zaak forever leaves its archiefactiedatum empty in Open Zaak."""
    forever, stays = closed_zaak(), closed_zaak()
    lijst = new_list(oab, api, [forever, stays], registry)
    forever_action = {**TAKE_OVER, "actionZaak": {"archiefactiedatum": None}}
    respond(
        oab,
        api,
        podiumd_env,
        lijst,
        reject(oab, api, "reviewer", lijst, [forever]),
        {str(forever["url"]): forever_action},
        "ready_to_review",
    )
    assert openzaak.get(str(forever["url"])).get("archiefactiedatum") is None


@pytest.mark.tc("ABC-019", "ABC-022")
@pytest.mark.source(
    "draaiboek ABC-019", "The archivist can reject the list; it goes back to the record manager with change requests."
)
@pytest.mark.scenario("""
    Given a vernietigingslijst of one closed zaak, accepted by the reviewer and handed to the archivist
    When the archivist rejects it, proposing to keep the zaak
    Then the list asks the record manager for changes
    When the record manager declines the proposal
    Then the list is back with the archivist
    And the zaak is still on the list
""")
def test_archivist_rejection_goes_back_and_returns_to_the_archivist(
    oab: Callable[[str], requests.Session],
    api: str,
    zaak: JsonObject,
    registry: ResourceRegistry,
    podiumd_env: Environment,
) -> None:
    """The archivist's rejection goes back to the record manager; declined, the list returns to the archivist unchanged."""
    lijst = new_list(oab, api, zaak, registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    expect_status(make_final(oab, api, lijst), HTTPStatus.CREATED, HTTPStatus.OK)
    rejection = reject(oab, api, "archivist", lijst, [zaak])
    assert list_status(oab, api, lijst) == "changes_requested"
    respond(oab, api, podiumd_env, lijst, rejection, {str(zaak["url"]): KEEP}, "ready_for_archivist")
    assert zaken_on(oab, api, lijst) == [zaak["url"]]


@pytest.mark.tc("ABC-020", "ABC-021")
@pytest.mark.source(
    "draaiboek ABC-021",
    "The record manager can agree with some of the archivist's proposals; the list returns to the archivist.",
)
@pytest.mark.scenario("""
    Given a vernietigingslijst of three closed zaken, accepted by the reviewer and handed to the archivist
    And the archivist rejected it, proposing to keep two of the zaken
    When the record manager agrees to one proposal and declines the other
    Then the list is back with the archivist
    And only the declined zaak and the third zaak are on the list
""")
def test_record_manager_takes_some_archivist_proposals_over(
    oab: Callable[[str], requests.Session],
    api: str,
    closed_zaak: Callable[[], JsonObject],
    registry: ResourceRegistry,
    podiumd_env: Environment,
) -> None:
    """Agreeing to one of the archivist's two proposals: that zaak leaves, the list returns to the archivist."""
    taken, declined, stays = closed_zaak(), closed_zaak(), closed_zaak()
    lijst = new_list(oab, api, [taken, declined, stays], registry)
    review(oab, api, "reviewer", lijst, decision="accepted")
    expect_status(make_final(oab, api, lijst), HTTPStatus.CREATED, HTTPStatus.OK)
    rejection = reject(oab, api, "archivist", lijst, [taken, declined])
    respond(
        oab,
        api,
        podiumd_env,
        lijst,
        rejection,
        {str(taken["url"]): TAKE_OVER, str(declined["url"]): KEEP},
        "ready_for_archivist",
    )
    assert sorted(map(str, zaken_on(oab, api, lijst))) == sorted([str(declined["url"]), str(stays["url"])])


@pytest.mark.tc("ABC-004")
@pytest.mark.source(
    "draaiboek ABC-004",
    "A saved list not yet offered for review can be edited by the record manager, also to add zaken.",
)
@pytest.mark.scenario("""
    Given a vernietigingslijst of one closed zaak, not yet offered for review
    When the record manager adds a second closed zaak
    Then both zaken are on the list
""")
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
@pytest.mark.source("draaiboek ABC-006", "A reviewer cannot change the list itself; that is the record manager's work.")
@pytest.mark.scenario("""
    Given a vernietigingslijst ready for review
    When the reviewer, the co-reviewer or the archivist renames the list
    Then Open Archiefbeheer refuses the change
""")
def test_only_the_record_manager_changes_the_list(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry, role: str
) -> None:
    """Reviewers, co-reviewers and the archivist cannot rename the list; that is the record manager's work.

    OAB answers 404 to a user who may not see the list, 403 to one who may see it.
    """
    lijst = new_list(oab, api, zaak, registry)
    changed = oab(role).patch(f"{api}/destruction-lists/{lijst}/", json={"name": registry.tagged("hernoemd")})
    expect_status(changed, *REFUSED, HTTPStatus.NOT_FOUND)


UPSTREAM_E2E = "upstream maykinmedia/open-archiefbeheer backend/src/openarchiefbeheer/destruction/tests/e2e"


def main_reviewer(oab: Callable[[str], requests.Session], api: str, lijst: str) -> object:
    """The username of the list's main reviewer."""
    detail = expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{lijst}/"), HTTPStatus.OK).json()
    reviewers = [a for a in entries(detail.get("assignees")) if a.get("role") == "main_reviewer"]
    return section(reviewers[0], "user").get("username") if reviewers else None


@pytest.mark.source(
    f"{UPSTREAM_E2E}/features/test_feature_list_reassign.py", "The record manager changes the reviewer of a list."
)
@pytest.mark.source(
    f"{UPSTREAM_E2E}/issues/test_841_reassign_when_changes_requested.py",
    "The reviewer can also be changed after the reviewer requested changes.",
)
@pytest.mark.scenario("""
    Given a vernietigingslijst ready for review
    When the record manager assigns it to another reviewer
    Then that user is the list's reviewer
    When that reviewer rejects the list
    Then the list asks the record manager for changes
    And the record manager can assign it back to the first reviewer
""")
def test_record_manager_assigns_another_reviewer(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """The record manager hands a list to review to another reviewer, and back once that one requested changes."""
    lijst = new_list(oab, api, zaak, registry)

    def assign(user: str) -> None:
        body = {
            "comment": "podiumd-tests",
            "assignee": {"user": user_pk(oab, api, "reviewer", user), "role": "main_reviewer"},
        }
        changed = oab("recordmanager").post(f"{api}/destruction-lists/{lijst}/update_assignee/", json=body)
        expect_status(changed, HTTPStatus.OK)

    assign("beheerder")
    assert str(main_reviewer(oab, api, lijst)).endswith("-beheerder")
    reject(oab, api, "beheerder", lijst, [zaak])
    assert list_status(oab, api, lijst) == "changes_requested"
    assign("reviewer")
    assert str(main_reviewer(oab, api, lijst)).endswith("-reviewer")


@pytest.mark.source(
    f"{UPSTREAM_E2E}/features/test_feature_list_delete.py",
    "A new list can be deleted; a list past status new cannot.",
)
@pytest.mark.scenario("""
    Given a new vernietigingslijst and a vernietigingslijst ready for review
    When the record manager deletes both
    Then the new list is deleted
    But deleting the list ready for review is refused
    And that list stays ready for review
""")
def test_only_a_new_list_can_be_deleted(
    oab: Callable[[str], requests.Session], api: str, closed_zaak: Callable[[], JsonObject], registry: ResourceRegistry
) -> None:
    """The record manager deletes a list that is still new; a list ready to review is refused."""
    new = new_list(oab, api, closed_zaak(), registry, ready=False)
    expect_status(oab("recordmanager").delete(f"{api}/destruction-lists/{new}/"), HTTPStatus.NO_CONTENT)
    expect_status(oab("recordmanager").get(f"{api}/destruction-lists/{new}/"), HTTPStatus.NOT_FOUND)
    ready = new_list(oab, api, closed_zaak(), registry)
    expect_status(oab("recordmanager").delete(f"{api}/destruction-lists/{ready}/"), *REFUSED)
    assert list_status(oab, api, ready) == "ready_to_review"


@pytest.mark.xfail(
    strict=True,
    reason="[open-archiefbeheer-6] Open Archiefbeheer 2.0.0 (also main): process_review_response reads item.zaak.url"
    " of every suggested item (prepopulate_selection_after_review_response); an item whose zaak left the zaken cache"
    " has zaak None, the task fails and the list stays changes_requested; open-archiefbeheer#1129",
)
@pytest.mark.source(
    f"{UPSTREAM_E2E}/features/test_feature_list_process_review.py",
    "test_zaak_removed_outside_process: a zaak deleted by something else does not break processing the review.",
)
@pytest.mark.scenario("""
    Given a vernietigingslijst of two closed zaken that the reviewer rejected, proposing to keep both
    And one zaak is deleted in Open Zaak and removed from Open Archiefbeheer's zaken
    When the record manager declines the proposal for the other zaak
    Then the answer is accepted
    And the list is ready for review again
""")
def test_review_is_processed_after_a_zaak_was_deleted_elsewhere(
    oab: Callable[[str], requests.Session],
    api: str,
    closed_zaak: Callable[[], JsonObject],
    registry: ResourceRegistry,
    podiumd_env: Environment,
    openzaak: ApiClient,
) -> None:
    """A zaak on a rejected list is deleted in Open Zaak and left OAB's cache; answering the review for the other works.

    OAB keeps the list item with the zaak's URL and zaak empty; the list must still go back to review.
    """
    gone, stays = closed_zaak(), closed_zaak()
    lijst = new_list(oab, api, [gone, stays], registry)
    review_pk = reject(oab, api, "reviewer", lijst, [gone, stays])
    delete_zaak(openzaak, str(gone["url"]))
    forget_zaken(podiumd_env, [str(gone["url"])])
    items = rows(oab("recordmanager").get(f"{api}/review-items/", params={"item-review-review": str(review_pk)}))
    zaak_of = {item["pk"]: section(section(item, "destructionListItem"), "zaak").get("url") for item in items}
    assert stays["url"] in zaak_of.values()
    responses = [{"reviewItem": pk, **KEEP} for pk, url in zaak_of.items() if url == stays["url"]]
    body = {"review": review_pk, "comment": "podiumd-tests", "itemsResponses": responses}
    answered = oab("recordmanager").post(f"{api}/review-responses/", json=body)
    expect_status(answered, HTTPStatus.CREATED)
    wait_until(
        lambda: list_status(oab, api, lijst) == "ready_to_review",
        timeout=60,
        description=f"list {lijst} ready_to_review",
    )


@pytest.mark.tc("ABC-031")
@pytest.mark.source("draaiboek ABC-031", "The reviewer may forward a list whether or not the co-reviewer has reacted.")
@pytest.mark.scenario("""
    Given a vernietigingslijst ready for review, with a co-reviewer who has not reacted
    When the reviewer accepts the list
    Then the list is internally reviewed
""")
def test_reviewer_forwards_without_the_coreviewer(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """With a co-reviewer assigned who has not reacted, the reviewer can still accept the list."""
    lijst = new_list(oab, api, zaak, registry)
    assign_coreviewer(oab, api, lijst)
    review(oab, api, "reviewer", lijst, decision="accepted")
    assert list_status(oab, api, lijst) == "internally_reviewed"


def _compose_list(page: Page, identificatie: str, naam: str) -> None:
    """Select the zaak, name the new list, assign the test reviewer and submit the dialog."""
    page.get_by_role("row", name=identificatie).get_by_role("checkbox").check()
    page.get_by_role("button", name="Vernietigingslijst opstellen").last.click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Naam").fill(naam)
    dialog.get_by_role("combobox", name="Reviewer").click()
    # The options are a listbox without option roles.
    dialog.get_by_role("listbox").get_by_text(f"{PREFIX}-reviewer", exact=True).click()
    dialog.get_by_label("Toelichting").fill("podiumd-tests")
    dialog.get_by_role("button", name="Vernietigingslijst opstellen").click()


@pytest.mark.ui
@pytest.mark.tc("ABC-002")
@REG_143
@pytest.mark.scenario("""
    Given the record manager is logged in to Open Archiefbeheer
    When the record manager selects a closed zaak and makes a vernietigingslijst of it for the reviewer
    Then the new list is shown
    And the list holds only that zaak
    When the record manager opens the list
    Then the page shows the list's name and the zaak
""")
def test_record_manager_creates_a_list_in_the_ui(
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
    _compose_list(page, identificatie, naam)
    expect(page.get_by_text(naam)).to_be_visible()
    lijsten = rows(oab("recordmanager").get(f"{api}/destruction-lists/", params={"name": naam}))
    lijst = next(str(found["uuid"]) for found in lijsten if found.get("name") == naam)
    assert zaken_on(oab, api, lijst) == [zaak["url"]]
    page.get_by_text(naam).click()
    expect(page.get_by_role("heading", name=naam)).to_be_visible()
    expect(page.get_by_text(identificatie).first).to_be_visible()


@pytest.mark.ui
@pytest.mark.tc("ABC-009", "ABC-010")
@REG_143
@pytest.mark.scenario("""
    Given a vernietigingslijst that the reviewer rejected with a proposal for its zaak
    When the record manager opens the list in Open Archiefbeheer
    Then the page shows the zaak
    And the page shows the reviewer's proposal
""")
def test_record_manager_sees_the_proposals_in_the_ui(
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
@pytest.mark.source("draaiboek ABC-005", "A new list can be assigned to a reviewer, who can then open the site.")
@pytest.mark.scenario("""
    Given a vernietigingslijst assigned to the reviewer
    When the reviewer logs in to Open Archiefbeheer
    Then the reviewer sees the list
""")
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


@REG_166
@pytest.mark.scenario("""
    Given a vernietigingslijst ready for review, with a co-reviewer
    When the co-reviewer gives feedback on the list
    Then the reviewer sees that feedback
""")
def test_coreviewer_feedback_reaches_the_reviewer(
    oab: Callable[[str], requests.Session], api: str, zaak: JsonObject, registry: ResourceRegistry
) -> None:
    """A co-reviewer added to the list gives feedback that the reviewer sees (TA reg-166 ABC-038..041)."""
    lijst = new_list(oab, api, zaak, registry)
    assign_coreviewer(oab, api, lijst)
    feedback = registry.tagged("medebeoordeling")
    co_review = {"destructionList": lijst, "listFeedback": feedback}
    expect_status(oab("coreviewer").post(f"{api}/destruction-list-co-reviews/", json=co_review), HTTPStatus.CREATED)
    seen = oab("reviewer").get(f"{api}/destruction-list-co-reviews/", params={"destruction_list__uuid": lijst})
    assert feedback in [str(r.get("listFeedback")) for r in entries(expect_status(seen, HTTPStatus.OK).json())]
