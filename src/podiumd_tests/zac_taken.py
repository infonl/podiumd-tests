"""ZAC's taken through its REST API: open, read, start, complete, assign and list them."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import AFGEROND
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import TASK_TIMEOUT
from podiumd_tests.zac import read_zaakafhandelparameters
from podiumd_tests.zac import save_zaakafhandelparameters

if TYPE_CHECKING:
    import requests

    from podiumd_tests.json_data import JsonObject


def _taak_refs(taken: list[JsonObject]) -> list[JsonObject]:
    return [{"taakId": taak["id"], "zaakUuid": taak["zaakUuid"]} for taak in taken]


def verdelen_taken(
    http: requests.Session, zac_url: str, taken: list[JsonObject], groep: str, behandelaar: str | None
) -> requests.Response:
    """Assign the taken from the werkvoorraad to the group and behandelaar; ZAC's answer, before its background job."""
    body = {
        "taken": _taak_refs(taken),
        "groepId": groep,
        "behandelaarGebruikersnaam": behandelaar,
        "reden": "podiumd-tests",
    }
    return http.put(f"{zac_url}/rest/taken/lijst/verdelen", json=body)


def vrijgeven_taken(http: requests.Session, zac_url: str, taken: list[JsonObject]) -> requests.Response:
    """Release the taken from the werkvoorraad; ZAC's answer, before its background job."""
    body = {"taken": _taak_refs(taken), "reden": "podiumd-tests"}
    return http.put(f"{zac_url}/rest/taken/lijst/vrijgeven", json=body)


def open_task(http: requests.Session, zac_url: str, zaak_uuid: str, name: str) -> JsonObject:
    """Wait until the zaak has an open task of this name, as ZAC lists it (with its formioFormulier)."""

    def found() -> JsonObject | None:
        tasks = get_entries(http, f"{zac_url}/rest/taken/zaak/{zaak_uuid}")
        open_tasks = (task for task in tasks if task.get("status") != AFGEROND)
        return next((task for task in open_tasks if task.get("naam") == name), None)

    return wait_until(found, timeout=TASK_TIMEOUT, description=f"open task {name!r} on zaak {zaak_uuid}")


def read_taak(http: requests.Session, zac_url: str, taak_id: str) -> JsonObject:
    """ZAC's view of a taak."""
    return cast("JsonObject", expect_status(http.get(f"{zac_url}/rest/taken/{taak_id}"), HTTPStatus.OK).json())


def taak_historie(http: requests.Session, zac_url: str, taak: JsonObject) -> list[JsonObject]:
    """Return ZAC's historie of the taak."""
    return get_entries(http, f"{zac_url}/rest/taken/{taak['id']}/historie")


def is_task_open(http: requests.Session, zac_url: str, task_id: str) -> bool:
    """ZAC reads the task, and not as AFGEROND."""
    response = http.get(f"{zac_url}/rest/taken/{task_id}")
    return response.status_code == HTTPStatus.OK and response.json().get("status") != AFGEROND


def complete_task(http: requests.Session, zac_url: str, task: JsonObject, data: JsonObject) -> JsonObject:
    """Complete a form task with its form's data, as ZAC's UI submits it; the completed task."""
    body = {**task, "taakdata": {**section(task, "taakdata"), **data}}
    return cast(
        "JsonObject", expect_status(http.patch(f"{zac_url}/rest/taken/complete", json=body), HTTPStatus.OK).json()
    )


def activate_human_tasks(
    http: requests.Session, zac_url: str, zaaktype_uuid: str, **plan_items: JsonObject
) -> JsonObject:
    """Switch every human task of the zaaktype version on, with these fields per plan item id; the saved parameters."""
    parameters = read_zaakafhandelparameters(http, zac_url, zaaktype_uuid)
    tasks = [
        {**task, "actief": True, **plan_items.get(str(section(task, "planItemDefinition").get("id")), {})}
        for task in entries(parameters.get("humanTaskParameters"))
    ]
    return save_zaakafhandelparameters(http, zac_url, {**parameters, "humanTaskParameters": tasks})


# The names of ZAC's CMMN human tasks (Generiek_zaakafhandelmodel.cmmn.xml); a zaakafhandelparameters switch turns
# each on.
AANVULLENDE_INFORMATIE = "Aanvullende informatie"
GOEDKEUREN = "Goedkeuren"
ADVIES_INTERN = "Advies intern"
ADVIES_EXTERN = "Advies extern"
DOCUMENT_VERZENDEN = "Document verzenden"


def human_tasks_offered(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the plan items of the human tasks ZAC offers to start on the zaak now."""
    return get_entries(http, f"{zac_url}/rest/planitems/zaak/{zaak['uuid']}/humanTaskPlanItems")


def start_human_task(
    http: requests.Session, zac_url: str, zaak: JsonObject, name: str, groep: str | None, **fields: object
) -> requests.Response:
    """Start the zaak's human task of this name for the group (None: without one), once ZAC offers it; ZAC's answer.

    ZAC starts a zaak's case, and the stage after the intake, in the background. fields: more of ZAC's
    RESTHumanTaskData (medewerker, fataledatum, toelichting, taakdata, taakStuurGegevens: no mail unless given).
    """

    def offered() -> JsonObject | None:
        return next((item for item in human_tasks_offered(http, zac_url, zaak) if item.get("naam") == name), None)

    plan_item = wait_until(offered, timeout=INDEX_TIMEOUT, description=f"{name!r} offered on {zaak['identificatie']}")
    body = {
        "planItemInstanceId": plan_item["id"],
        "groep": {"id": groep, "naam": groep} if groep else None,
        "taakdata": {},
        "taakStuurGegevens": {"sendMail": False},
        **fields,
    }
    return http.post(f"{zac_url}/rest/planitems/doHumanTaskPlanItem", json=body)


def started_taak(
    http: requests.Session, zac_url: str, zaak: JsonObject, name: str, to: tuple[str, str], **fields: object
) -> JsonObject:
    """Start the zaak's human task for (group, behandelaar) with start_human_task; the open task."""
    groep, behandelaar = to
    medewerker = {"id": behandelaar, "naam": behandelaar}
    response = start_human_task(http, zac_url, zaak, name, groep, medewerker=medewerker, **fields)
    expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    return open_task(http, zac_url, str(zaak["uuid"]), name)


def toekennen_taak(http: requests.Session, zac_url: str, taak: JsonObject, groep: str, behandelaar: str) -> None:
    """Assign the open taak to the group and behandelaar, as from the taak."""
    body = {
        "taakId": taak["id"],
        "zaakUuid": taak["zaakUuid"],
        "groepId": groep,
        "behandelaarId": behandelaar,
        "reden": "podiumd-tests",
    }
    expect_status(http.patch(f"{zac_url}/rest/taken/toekennen", json=body), HTTPStatus.NO_CONTENT, HTTPStatus.OK)


def wijzig_taak(http: requests.Session, zac_url: str, taak_id: str, **fields: object) -> None:
    """Change these fields (fataledatum, toelichting) of the open taak, as its form saves them."""
    taak = expect_status(http.get(f"{zac_url}/rest/taken/{taak_id}"), HTTPStatus.OK).json()
    expect_status(http.put(f"{zac_url}/rest/taken/taakdata", json={**taak, **fields}), HTTPStatus.OK)
