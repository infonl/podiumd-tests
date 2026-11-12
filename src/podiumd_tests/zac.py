"""ZAC's REST API without a browser, and its zaakafhandelparameters."""

from __future__ import annotations

import csv
import io
import json
import re
import secrets
import time

from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.bootstrap.names import ZAC_BASE_ROLES
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.oidc import LOGIN_PATHS
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_besluit
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# The status ZAC gives a completed or ended task.
AFGEROND = "AFGEROND"
# ZAC's own address inside its pod.
IN_POD = "http://localhost:8080"
# ZAC reindexes in the request, page by page; tens of thousands of zaken take minutes.
REINDEX_TIMEOUT = 1800
# Objecten notifies, Open Notificaties delivers to ZAC, and ZAC starts the zaak and its case.
PRODUCTAANVRAAG_TIMEOUT = 120
# ZAC's handling of a productaanvraag.
PRODUCTAANVRAAG_SOURCE = "upstream infonl/dimpact-zaakafhandelcomponent src/main/kotlin/nl/info/zac/productaanvraag"
# The communicatiekanaal of a zaak from a productaanvraag.
E_FORMULIER = "E-formulier"
# ZAC indexes a zaak in Solr after Open Notificaties tells it about the change.
INDEX_TIMEOUT = 60
# Open Notificaties delivers a change in Open Zaak to ZAC.
NOTIFICATION_TIMEOUT = 60
# A BPMN process reaches its next user task after ZAC's service tasks have run.
TASK_TIMEOUT = 30
# ZAC assigns and releases list selections in a background job, and indexes taken in Solr; both lag under load.
LIST_TIMEOUT = 120


def zac_session(env: Environment, username: str, password: str) -> requests.Session:
    """Return a session on ZAC's REST API, logged in through Keycloak's form."""
    http = env.session()
    form_login(http, env.profile.urls["zac"] + LOGIN_PATHS["zac"], username, password)
    return http


def logged_in_user(http: requests.Session, zac_url: str) -> JsonObject:
    """ZAC's view of the session's user: id, naam (as the historie names it), groupIds and roles."""
    return cast("JsonObject", expect_status(http.get(f"{zac_url}/rest/identity/loggedInUser"), HTTPStatus.OK).json())


def user_groups(http: requests.Session, zac_url: str) -> list[str]:
    """Return the ids of the groups ZAC knows the session's user in."""
    return strings(logged_in_user(http, zac_url)["groupIds"])


def zaakafhandelparameters(http: requests.Session, zac_url: str, identificatie: str | None = None) -> list[JsonObject]:
    """ZAC's zaakafhandelparameters of every version of the zaaktype, or of every zaaktype ZAC handles.

    ZAC also lists its catalogus' zaaktypen without zaakafhandelparameters, with id null; those are left out.
    """
    found = get_entries(http, f"{zac_url}/rest/zaakafhandelparameters")
    return [
        parameters
        for parameters in found
        if parameters.get("id") is not None
        and identificatie in {None, section(parameters, "zaaktype").get("identificatie")}
    ]


def read_zaakafhandelparameters(http: requests.Session, zac_url: str, zaaktype_uuid: str) -> JsonObject:
    """Return ZAC's zaakafhandelparameters of one zaaktype version, complete for a save; id None when it has none."""
    response = http.get(f"{zac_url}/rest/zaakafhandelparameters/{zaaktype_uuid}")
    return cast("JsonObject", expect_status(response, HTTPStatus.OK).json())


def save_zaakafhandelparameters(http: requests.Session, zac_url: str, parameters: JsonObject) -> JsonObject:
    """Save zaakafhandelparameters as ZAC's beheerder; the saved ones."""
    return cast(
        "JsonObject", expect_status(put_zaakafhandelparameters(http, zac_url, parameters), HTTPStatus.OK).json()
    )


def put_zaakafhandelparameters(http: requests.Session, zac_url: str, parameters: JsonObject) -> requests.Response:
    """Send zaakafhandelparameters to save; ZAC's answer."""
    return http.put(f"{zac_url}/rest/zaakafhandelparameters", json=parameters)


def copied_zaakafhandelparameters(http: requests.Session, zac_url: str, zaaktype_uuid: str) -> JsonObject:
    """Wait until ZAC has zaakafhandelparameters for a new zaaktype version; return them.

    ZAC copies them from the newest version with the same omschrijving when Open Notificaties delivers an update of
    the published version.
    """

    def copied() -> JsonObject | None:
        found = read_zaakafhandelparameters(http, zac_url, zaaktype_uuid)
        return None if found.get("id") is None else found

    return wait_until(copied, timeout=NOTIFICATION_TIMEOUT, description=f"zaakafhandelparameters of {zaaktype_uuid}")


# ZAC's CMMN model, with the user events INTAKE_AFRONDEN and ZAAK_AFHANDELEN.
CASE_DEFINITION = "generiek-zaakafhandelmodel"


def configure_zaaktype(
    http: requests.Session, zac_url: str, zaaktype_uuid: str, groep: str, **fields: object
) -> JsonObject:
    """Save valide zaakafhandelparameters for a zaaktype version: ZAC's CMMN model, groep and fields; the saved ones.

    The niet-ontvankelijk resultaattype is the zaaktype's first; ZAC runs a user event only with a parameter for it.
    """
    response = http.get(f"{zac_url}/rest/zaakafhandelparameters/case-definitions/{CASE_DEFINITION}")
    definition = cast("JsonObject", expect_status(response, HTTPStatus.OK).json())
    events = [
        {"id": event["id"], "naam": event["naam"]} for event in entries(definition["userEventListenerDefinitions"])
    ]
    first = get_entries(http, f"{zac_url}/rest/zaakafhandelparameters/resultaattypes/{zaaktype_uuid}")[0]
    parameters = {
        **read_zaakafhandelparameters(http, zac_url, zaaktype_uuid),
        "caseDefinition": {"key": CASE_DEFINITION, "naam": definition["naam"]},
        "defaultGroepId": groep,
        "zaakNietOntvankelijkResultaattype": first,
        "userEventListenerParameters": events,
        **fields,
    }
    return save_zaakafhandelparameters(http, zac_url, parameters)


# Fields that differ between the zaakafhandelparameters of two versions of a zaaktype.
VERSION_FIELDS = frozenset(("id", "creatiedatum", "zaaktype"))


def comparable(value: object) -> object:
    """Return the zaakafhandelparameters, or a part, without VERSION_FIELDS, lists sorted, a resultaattype by naam.

    A new version has its own resultaattypen, which ZAC maps by omschrijving.
    """
    if isinstance(value, list):
        return sorted((comparable(item) for item in cast("list[object]", value)), key=repr)
    if not isinstance(value, dict):
        return value
    found = cast("JsonObject", value)
    if "naamGeneriek" in found:
        return found.get("naam")
    return {key: comparable(item) for key, item in found.items() if key not in VERSION_FIELDS}


def behandelaar_groups(http: requests.Session, zac_url: str, *omschrijvingen: str) -> set[str]:
    """Return the ids of the groups PABC authorises as behandelaar of zaken of each zaaktype.

    One zaaktype: ZAC's list for a zaak or taak; more: its list for verdelen a selection.
    """
    if len(omschrijvingen) == 1:
        url = f"{zac_url}/rest/identity/zaaktype/{omschrijvingen[0]}/behandelaar-groups"
        return {str(group["id"]) for group in get_entries(http, url)}
    body = {"zaaktypeDescriptions": list(omschrijvingen)}
    response = expect_status(http.post(f"{zac_url}/rest/identity/behandelaar-groups", json=body), HTTPStatus.OK)
    return {str(group["id"]) for group in entries(response.json())}


def active_groups(http: requests.Session, zac_url: str) -> set[str]:
    """Return the ids of the groups ZAC offers: Keycloak's groups without attribute active false."""
    return {str(group["id"]) for group in get_entries(http, f"{zac_url}/rest/identity/groups")}


def group_members(http: requests.Session, zac_url: str, groep: str) -> set[str]:
    """Return the usernames ZAC offers as behandelaar in the group: its Keycloak members."""
    return {str(user["id"]) for user in get_entries(http, f"{zac_url}/rest/identity/groups/{groep}/users")}


# Fields of ZAC's inrichtingscheck that its verdict valide does not require.
NOT_REQUIRED_FOR_VALIDE = {
    "valide",
    "heeftWaarschuwingen",
    "besluittypeAanwezig",
    "isZaakspecifiekeAutorisatieEigenschapAanwezig",
    "isZaakspecifiekeAutorisatieRoltypeAanwezig",
}


def inrichtingscheck_problems(check: JsonObject) -> list[str]:
    """Return the fields of ZAC's inrichtingscheck of one zaaktype that make it invalid, and its warnings."""
    problems = [field for field, value in check.items() if value is False and field not in NOT_REQUIRED_FOR_VALIDE]
    counts = {field: value for field, value in check.items() if field.startswith("aantal")}
    problems += [f"{field}={value}" for field, value in counts.items() if value != 1]
    if check.get("resultaattypesMetVerplichtBesluit") and not check.get("besluittypeAanwezig"):
        problems.append("besluittypeAanwezig")
    if check.get("heeftWaarschuwingen"):
        problems.append("heeftWaarschuwingen")
    if not problems and not check.get("valide"):
        problems.append("valide")
    return sorted(problems)


# The indicatie of a zaak whose ontvangstbevestiging ZAC has not sent.
BEVESTIGING_NIET_VERSTUURD = "ONTVANGSTBEVESTIGING_NIET_VERSTUURD"


def is_confirmation_sent(confirmation: JsonObject) -> bool:
    """ZAC sends this automaticEmailConfirmation: enabled, with a template and a sender."""
    return bool(confirmation.get("enabled") and confirmation.get("templateName") and confirmation.get("emailSender"))


def mail_address(env: Environment, afzender: str) -> str:
    """Return the address of an afzender of automaticEmailConfirmation: GEMEENTE is ZAC's GEMEENTE_MAIL."""
    return env.variable("zac", "GEMEENTE_MAIL") if afzender == "GEMEENTE" else afzender


def is_confirmation_on(http: requests.Session, zac_url: str, identificatie: str) -> bool:
    """ZAC sends its ontvangstbevestiging for productaanvragen of every version of the zaaktype."""
    found = zaakafhandelparameters(http, zac_url, identificatie)
    return bool(found) and all(
        is_confirmation_sent(section(parameters, "automaticEmailConfirmation")) for parameters in found
    )


# The reason ZAC always offers for aborting a zaak.
NIET_ONTVANKELIJK = "ZAAK_NIET_ONTVANKELIJK"
# The toelichting of the eindstatus ZAC sets when it aborts a zaak for that reason.
NIET_ONTVANKELIJK_REDEN = "Zaak is niet ontvankelijk"


def zaak_body(parameters: JsonObject, **fields: object) -> JsonObject:
    """ZAC's request to start a zaak of the zaaktype of these zaakafhandelparameters, in their default group.

    With a startdatum (today unless given) and communicatiekanaal, as ZAC's UI always sends them.
    """
    groep = {"id": parameters["defaultGroepId"], "naam": str(parameters["defaultGroepId"])}
    defaults = {"startdatum": date.today().isoformat(), "communicatiekanaal": "E-mail"}  # noqa: DTZ011  # a local date
    return {"zaak": {"zaaktype": parameters["zaaktype"], "groep": groep, **defaults, **fields}}


def create_zaak(http: requests.Session, zac_url: str, parameters: JsonObject, **fields: object) -> JsonObject:
    """Return a zaak started in ZAC (zaak_body), as ZAC shows it."""
    return start_zaak(http, zac_url, zaak_body(parameters, **fields))


def start_zaak(http: requests.Session, zac_url: str, body: JsonObject) -> JsonObject:
    """Return the zaak ZAC starts for this request (RestZaakAanmaakGegevens), as ZAC shows it."""
    response = http.post(f"{zac_url}/rest/zaken/zaak", json=body)
    created = cast("JsonObject", expect_status(response, HTTPStatus.OK).json())
    if "uuid" in created:
        return created
    # ZAC 5.9 answers only the identificatie.
    found = http.get(f"{zac_url}/rest/zaken/zaak/id/{created['identificatie']}")
    return cast("JsonObject", expect_status(found, HTTPStatus.OK).json())


def attempt_zaak(
    http: requests.Session, zac_url: str, openzaak: ApiClient, registry: ResourceRegistry, body: JsonObject
) -> tuple[requests.Response, list[str]]:
    """Ask ZAC to start the zaak of this request; its answer and the identificaties of the zaken Open Zaak got.

    The zaken are found by the request's omschrijving; cleanup deletes them.
    """
    response = http.post(f"{zac_url}/rest/zaken/zaak", json=body)
    omschrijving = section(body, "zaak").get("omschrijving")
    found = [zaak for zaak in recent_zaken(openzaak) if zaak.get("omschrijving") == omschrijving]
    for zaak in found:
        clean_up_zaak(http, zac_url, openzaak, registry, zaak)
    return response, [str(zaak["identificatie"]) for zaak in found]


def read_zaak(http: requests.Session, zac_url: str, uuid: str) -> JsonObject:
    """ZAC's view of a zaak."""
    return cast("JsonObject", expect_status(http.get(f"{zac_url}/rest/zaken/zaak/{uuid}"), HTTPStatus.OK).json())


def can_open_zaak(http: requests.Session, zac_url: str, zaak: JsonObject) -> bool:
    """Return whether the session's user may open the zaak in ZAC; raise on an answer other than 200, 401 or 403."""
    response = http.get(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}", allow_redirects=False)
    return expect_status(response, HTTPStatus.OK, *REFUSED).status_code == HTTPStatus.OK


def zaak_historie(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return ZAC's historie of the zaak, newest first."""
    return get_entries(http, f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/historie")


def attribuut_historie(http: requests.Session, zac_url: str, zaak: JsonObject, label: str) -> list[tuple[object, ...]]:
    """Return the zaak's historie lines of one attribuut as (oude waarde, nieuwe waarde, toelichting), newest first."""
    return [
        (line.get("oudeWaarde"), line.get("nieuweWaarde"), line.get("toelichting"))
        for line in zaak_historie(http, zac_url, zaak)
        if line.get("attribuutLabel") == label
    ]


def bag_object(http: requests.Session, zac_url: str, soort: str, identificatie: str) -> JsonObject:
    """ZAC's view of the BAG object of this soort (ADRES, PAND, ...), as a new zaak takes it in bagObjecten."""
    response = http.get(f"{zac_url}/rest/bag/{soort}/{identificatie}")
    return cast("JsonObject", expect_status(response, HTTPStatus.OK).json())


def zaak_bag_objecten(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the BAG objects linked to the zaak, each under zaakobject."""
    return get_entries(http, f"{zac_url}/rest/bag/zaak/{zaak['uuid']}")


def koppel_bag_object(http: requests.Session, zac_url: str, zaak: JsonObject, bag: JsonObject) -> requests.Response:
    """Link the BAG object (bag_object) to the zaak; ZAC links one only once. ZAC's answer."""
    return http.post(f"{zac_url}/rest/bag", json={"zaakUuid": zaak["uuid"], "zaakobject": bag})


def ontkoppel_bag_object(
    http: requests.Session, zac_url: str, zaak: JsonObject, linked: JsonObject, reden: str
) -> requests.Response:
    """Unlink a BAG object of zaak_bag_objecten from the zaak, with the reden; ZAC's answer."""
    body = {**linked, "zaakUuid": zaak["uuid"], "redenWijzigen": reden}
    return http.delete(f"{zac_url}/rest/bag", json=body)


def zaaklocatie(
    http: requests.Session, zac_url: str, zaak: JsonObject, geometrie: JsonObject | None, reden: str
) -> requests.Response:
    """Set the zaak's locatie to the RestGeometry, or remove it with None, with the reden; ZAC's answer."""
    body = {"geometrie": geometrie, "reden": reden}
    return http.patch(f"{zac_url}/rest/zaken/{zaak['uuid']}/zaaklocatie", json=body)


def user_events_offered(http: requests.Session, zac_url: str, zaak_uuid: str) -> list[JsonObject]:
    """Return the plan items of the CMMN user events ZAC offers on the zaak now.

    ZAC offers INTAKE_AFRONDEN and ZAAK_AFHANDELEN only while no human task of the stage is open.
    """
    return get_entries(http, f"{zac_url}/rest/planitems/zaak/{zaak_uuid}/userEventListenerPlanItems")


def user_event(http: requests.Session, zac_url: str, zaak_uuid: str, actie: str, **fields: object) -> requests.Response:
    """Run a CMMN user event of the zaak: INTAKE_AFRONDEN or ZAAK_AFHANDELEN, at its open plan item; ZAC's answer."""
    items = user_events_offered(http, zac_url, zaak_uuid)
    found = [item for item in items if item.get("userEventListenerActie") == actie]
    if not found:
        msg = f"zaak {zaak_uuid} offers no {actie}: {[item.get('naam') for item in items]}"
        raise AssertionError(msg)
    body = {"zaakUuid": zaak_uuid, "planItemInstanceId": found[0]["id"], "actie": actie, **fields}
    return http.post(f"{zac_url}/rest/planitems/doUserEventListenerPlanItem", json=body)


def afronden_intake(http: requests.Session, zac_url: str, zaak: JsonObject) -> None:
    """Finish the zaak's intake as ontvankelijk: status In behandeling, with ZAAK_AFHANDELEN offered."""
    response = user_event(http, zac_url, str(zaak["uuid"]), "INTAKE_AFRONDEN", zaakOntvankelijk=True)
    expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)


def resultaattypen(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the resultaattypen ZAC offers for the zaak's zaaktype."""
    zaaktype = section(zaak, "zaaktype")["uuid"]
    response = http.get(f"{zac_url}/rest/zaken/resultaattypes/{zaaktype}")
    return entries(expect_status(response, HTTPStatus.OK).json())


def _resultaattype_without_besluit(http: requests.Session, zac_url: str, zaak: JsonObject) -> str:
    """Return the id of the zaaktype's first resultaattype that needs no besluit."""
    found = (item for item in resultaattypen(http, zac_url, zaak) if not item.get("besluitVerplicht"))
    return str(next(found)["id"])


def afhandelen(
    http: requests.Session, zac_url: str, zaak: JsonObject, resultaattype: str | None = None, **fields: object
) -> requests.Response:
    """Run ZAAK_AFHANDELEN of a CMMN zaak with the resultaattype, by default one that needs no besluit; ZAC's answer.

    fields are further RestUserEventListenerData, such as restMailGegevens for the afhandelmail and brondatum.
    """
    chosen = resultaattype or _resultaattype_without_besluit(http, zac_url, zaak)
    body = {"resultaattypeUuid": chosen, "resultaatToelichting": "podiumd-tests", **fields}
    return user_event(http, zac_url, str(zaak["uuid"]), "ZAAK_AFHANDELEN", **body)


def zoned_brondatum(day: str) -> str:
    """Return the date as ZAC reads a brondatum: a zoned date-time, as its UI sends it; it refuses a plain date."""
    return f"{day}T00:00:00Z"


def brondatum_zetten(http: requests.Session, zac_url: str, zaak: JsonObject, day: str) -> requests.Response:
    """Set the brondatum of the closed zaak, whose resultaat derives it from an eigenschap, to the day; ZAC's answer."""
    body = {"zaakUuid": zaak["uuid"], "actie": "BRONDATUM_ZETTEN", "brondatum": zoned_brondatum(day)}
    return http.post(f"{zac_url}/rest/planitems/doUserEventListenerPlanItem", json=body)


def afbreken(
    http: requests.Session, zac_url: str, zaak: JsonObject, reden: str = NIET_ONTVANKELIJK
) -> requests.Response:
    """Abort the zaak for the zaakbeeindigreden of this id, by default niet ontvankelijk; ZAC's answer."""
    body = {"zaakbeeindigRedenId": reden}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/afbreken", json=body)


def end_process(http: requests.Session, zac_url: str, uuid: str) -> None:
    """End the zaak's BPMN process and its open taken by afbreken, where ZAC allows it: on an open, not heropende zaak.

    ZAC 5.9.1 keeps the process when afsluiten closes the zaak, and when the zaak is deleted in Open Zaak (zac-14).
    afbreken of a zaaktype without niet-ontvankelijk resultaattype leaves the zaak open.
    """
    response = http.get(f"{zac_url}/rest/zaken/zaak/{uuid}")
    if response.status_code == HTTPStatus.NOT_FOUND:
        return
    zaak = cast("JsonObject", expect_status(response, HTTPStatus.OK).json())
    is_open = zaak.get("isOpen") and not zaak.get("isHeropend")
    if is_open and zaak.get("isProcesGestuurd") and section(zaak, "rechten").get("afbreken"):
        expect_status(afbreken(http, zac_url, zaak), HTTPStatus.OK)


def end_process_at_cleanup(http: requests.Session, zac_url: str, registry: ResourceRegistry, zaak: JsonObject) -> None:
    """Run end_process at cleanup; registered after the zaak's delete, it runs before it."""
    uuid = str(zaak["uuid"])
    registry.add(f"BPMN process of zaak {zaak['identificatie']}", lambda: end_process(http, zac_url, uuid))


def clean_up_zaak(  # noqa: PLR0913  # the zaak, its two APIs and the cleanup
    http: requests.Session,
    zac_url: str,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    zaak: JsonObject,
    *,
    with_documents: bool = True,
) -> None:
    """Delete, at cleanup, the zaak ZAC shows from Open Zaak, after end_process."""
    url = openzaak.url(f"{ZAKEN}/zaken/{zaak['uuid']}")
    registry.add(f"zaak {zaak['identificatie']}", lambda: delete_zaak(openzaak, url, with_documents=with_documents))
    end_process_at_cleanup(http, zac_url, registry, zaak)


def afsluiten(
    http: requests.Session, zac_url: str, zaak: JsonObject, resultaattype: str | None = None
) -> requests.Response:
    """Close the zaak with the resultaattype, by default one that needs no besluit, as for a BPMN zaak; ZAC's answer.

    Ends a BPMN zaak's process first (end_process): ZAC keeps it on the closed zaak, where afbreken is refused.
    """
    end_process(http, zac_url, str(zaak["uuid"]))
    chosen = resultaattype or _resultaattype_without_besluit(http, zac_url, zaak)
    body = {"reden": "podiumd-tests", "resultaattypeUuid": chosen}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/afsluiten", json=body)


# ZAC took 9 s to over 15 s to save zaakgegevens with a new group and behandelaar in a parallel run on minikube.
WIJZIG_TIMEOUT = 60


def wijzig_zaak(http: requests.Session, zac_url: str, zaak: JsonObject, **fields: object) -> requests.Response:
    """Change these fields (RestZaakCreateData) of the zaak, with a reden; ZAC's answer."""
    data = {"omschrijving": zaak["omschrijving"], "zaaktype": zaak["zaaktype"], **fields}
    body = {"zaak": data, "reden": "podiumd-tests"}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}", json=body, timeout=WIJZIG_TIMEOUT)


def assignment(item: JsonObject) -> tuple[object, object]:
    """(group id, behandelaar id) of ZAC's view of a zaak or task."""
    return section(item, "groep").get("id"), section(item, "behandelaar").get("id")


def listed_assignment(item: JsonObject) -> tuple[object, object]:
    """(group id, behandelaar id) of a zaak as ZAC's search lists it."""
    return item.get("groepId"), item.get("behandelaarGebruikersnaam")


def verdelen(
    http: requests.Session, zac_url: str, uuids: list[str], groep: str, behandelaar: str | None
) -> requests.Response:
    """Assign the zaken from the werkvoorraad to the group and behandelaar; ZAC's answer, before its background job."""
    body = {"uuids": uuids, "groepId": groep, "behandelaarGebruikersnaam": behandelaar, "reden": "podiumd-tests"}
    return http.put(f"{zac_url}/rest/zaken/lijst/verdelen", json=body)


def vrijgeven(http: requests.Session, zac_url: str, uuids: list[str]) -> requests.Response:
    """Release the zaken from the werkvoorraad; ZAC's answer, before its background job."""
    return http.put(f"{zac_url}/rest/zaken/lijst/vrijgeven", json={"uuids": uuids, "reden": "podiumd-tests"})


def toekennen_mij(http: requests.Session, zac_url: str, zaak: JsonObject, groep: str) -> requests.Response:
    """Assign the zaak to the group and the session's user from the werkvoorraad; ZAC's answer."""
    body = {"zaakUUID": zaak["uuid"], "groepId": groep, "reden": "podiumd-tests"}
    return http.put(f"{zac_url}/rest/zaken/lijst/toekennen/mij", json=body)


def taak_toekennen_mij(http: requests.Session, zac_url: str, taak: JsonObject) -> requests.Response:
    """Assign the taak to the session's user from the werkvoorraad; ZAC's answer."""
    body = {"taakId": taak["id"], "zaakUuid": taak["zaakUuid"], "groepId": "", "reden": "podiumd-tests"}
    return http.patch(f"{zac_url}/rest/taken/lijst/toekennen/mij", json=body)


# ZAC's access rules (OPA policies), the source of the expected rights per role.
POLICIES = "upstream infonl/dimpact-zaakafhandelcomponent src/main/resources/policies"


def rights_of(role: str, least_roles: Mapping[str, str | None]) -> dict[str, bool]:
    """Each right of least_roles (right: the least base role with it, None for none) that the base role has.

    A base role has the rights of the base roles before it in ZAC_BASE_ROLES.
    """
    held = set(ZAC_BASE_ROLES[: ZAC_BASE_ROLES.index(role) + 1])
    return {right: least in held for right, least in least_roles.items()}


def clear_ztc_cache(http: requests.Session, zac_url: str) -> None:
    """Clear ZAC's cache of Open Zaak's catalogus types, as ZAC's beheerder."""
    expect_status(http.delete(f"{zac_url}/rest/health-check/ztc-cache"), HTTPStatus.OK)


def besluittypen(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the besluittypen ZAC offers for the zaak's zaaktype today."""
    zaaktype = section(zaak, "zaaktype")["uuid"]
    response = http.get(f"{zac_url}/rest/zaken/besluittypes/{zaaktype}")
    return entries(expect_status(response, HTTPStatus.OK).json())


def vastleggen_besluit(
    http: requests.Session, zac_url: str, zaak: JsonObject, besluittype: JsonObject, **fields: object
) -> requests.Response:
    """Record a besluit of the besluittype on the zaak, with these RestBesluitCreateData fields; ZAC's answer."""
    body = {"zaakUuid": zaak["uuid"], "besluittypeUuid": besluittype["id"], **fields}
    return http.post(f"{zac_url}/rest/zaken/besluit", json=body)


def recorded_besluit(  # noqa: PLR0913, PLR0917  # the besluit, its zaak and its cleanup
    http: requests.Session,
    zac_url: str,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    zaak: JsonObject,
    besluittype: JsonObject,
    **fields: object,
) -> JsonObject:
    """Record a besluit on the zaak, valid from today; cleanup deletes it before the zaak, which Open Zaak keeps."""
    body = {"ingangsdatum": date.today().isoformat(), "toelichting": "podiumd-tests", **fields}  # noqa: DTZ011  # ZAC's local date
    created = expect_status(vastleggen_besluit(http, zac_url, zaak, besluittype, **body), HTTPStatus.OK).json()
    url = str(created["url"])
    registry.add(f"besluit {created['identificatie']}", lambda: delete_besluit(openzaak, url))
    return cast("JsonObject", created)


def afzenders(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the afzenders ZAC offers for mail from the zaak."""
    return get_entries(http, f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/afzender")


def zaak_mailtemplate(http: requests.Session, zac_url: str, zaak: JsonObject, mail: str) -> JsonObject | None:
    """Return the mailtemplate ZAC offers for this mail (ZAAK_AFGEHANDELD, ...) of the zaak; None when it has none."""
    response = expect_status(
        http.get(f"{zac_url}/rest/mailtemplates/{mail}/{zaak['uuid']}"), HTTPStatus.OK, HTTPStatus.NO_CONTENT
    )
    return cast("JsonObject", response.json()) if response.content else None


def send_mail(
    http: requests.Session, zac_url: str, zaak: JsonObject, mail: JsonObject, *, acknowledge: bool = False
) -> requests.Response:
    """Send a mail from the zaak (RestMailGegevens), or its ontvangstbevestiging with acknowledge; ZAC's answer."""
    return http.post(f"{zac_url}/rest/mail/{'acknowledge' if acknowledge else 'send'}/{zaak['uuid']}", json=mail)


def koppel(
    http: requests.Session, zac_url: str, zaak: JsonObject, ander: JsonObject, relatie: str
) -> requests.Response:
    """Link the other zaak to the zaak as GERELATEERD, HOOFDZAAK or DEELZAAK (of the other zaak); ZAC's answer."""
    body = {"zaakUuid": zaak["uuid"], "teKoppelenZaakUuid": ander["uuid"], "relatieType": relatie}
    return http.patch(f"{zac_url}/rest/zaken/zaak/koppel", json=body)


def ontkoppel(  # noqa: PLR0913, PLR0917  # the fields of ZAC's request
    http: requests.Session, zac_url: str, zaak: JsonObject, ander: JsonObject, relatie: str, reden: str
) -> requests.Response:
    """Unlink the other zaak from the zaak; ZAC's answer."""
    body = {
        "zaakUuid": zaak["uuid"],
        "gekoppeldeZaakIdentificatie": ander["identificatie"],
        "relatieType": relatie,
        "reden": reden,
    }
    return http.patch(f"{zac_url}/rest/zaken/zaak/ontkoppel", json=body)


# ZAC's relatieType of two zaken linked as related.
GERELATEERD = "GERELATEERD"


def koppel_zoekresultaat(
    http: requests.Session, zac_url: str, zaak: JsonObject, ander: JsonObject, relatie: str
) -> JsonObject | None:
    """Return the other zaak as ZAC's search for zaken to link to the zaak finds it, or None.

    Matched by uuid: ZAC's index can hold deleted zaken whose identificatie Open Zaak gave out again (open-zaak-1).
    """
    body = {"zoekZaakIdentifier": ander["identificatie"], "relationType": relatie, "page": 0, "rows": 10}
    response = http.put(f"{zac_url}/rest/zaken/gekoppelde-zaken/{zaak['uuid']}/zoek-koppelbare-zaken", json=body)
    found = entries(expect_status(response, HTTPStatus.OK).json().get("resultaten"))
    return next((item for item in found if item.get("id") == ander["uuid"]), None)


def person_lookup(http: requests.Session, zac_url: str, bsn: str) -> list[JsonObject]:
    """ZAC's person lookup by BSN."""
    response = http.put(f"{zac_url}/rest/klanten/personen", json={"bsn": bsn})
    return entries(cast("JsonObject", expect_status(response, HTTPStatus.OK).json())["resultaten"])


def person_key(http: requests.Session, zac_url: str, bsn: str) -> str:
    """ZAC's temporaryPersonId for a BSN, from its person lookup; ZAC's API takes it instead of the BSN."""
    return str(person_lookup(http, zac_url, bsn)[0]["temporaryPersonId"])


def send_with_person(
    http: requests.Session, zac_url: str, bsn: str, send: Callable[[JsonObject], requests.Response]
) -> requests.Response:
    """send(the person's BetrokkeneIdentificatie); once more with a fresh lookup when ZAC answers 410.

    ZAC 5.4.5 keeps handing out a temporaryPersonId it forgot 12 h after its last read;
    the 410 clears it, as for a user who tries again.
    """

    def attempt() -> requests.Response:
        return send({"type": "BSN", "temporaryPersonId": person_key(http, zac_url, bsn)})

    response = attempt()
    return attempt() if response.status_code == HTTPStatus.GONE else response


def recent_zaken(openzaak: ApiClient) -> list[JsonObject]:
    """Return the zaken in Open Zaak started since yesterday."""
    # ZAC dates the zaak in Dutch time: around midnight a day after the UTC date.
    since = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    return openzaak.list(f"{ZAKEN}/zaken", {"startdatum__gte": since})


def productaanvraag_zaken(openzaak: ApiClient, kenmerk: str) -> list[JsonObject]:
    """Return the zaken started since yesterday with the productaanvraag's kenmerk in the toelichting."""
    return [zaak for zaak in recent_zaken(openzaak) if kenmerk in str(zaak.get("toelichting") or "")]


def productaanvraag_zaak(
    openzaak: ApiClient, registry: ResourceRegistry, kenmerk: str, timeout: float = PRODUCTAANVRAAG_TIMEOUT
) -> JsonObject:
    """Return the zaak ZAC starts for a productaanvraag, with its kenmerk in the toelichting; cleanup deletes it.

    openzaak: a client that may read and delete zaken of the zaaktype (bootstrap openzaak-client-productaanvraag).
    """

    def started() -> JsonObject | None:
        return next(iter(productaanvraag_zaken(openzaak, kenmerk)), None)

    def delete() -> None:
        zaak = started()
        if zaak:
            delete_zaak(openzaak, str(zaak["url"]), with_documents=True)

    # Registered before the wait, so a zaak started after a timeout goes too.
    registry.add(f"zaak for productaanvraag {kenmerk}", delete)
    return wait_until(started, timeout=timeout, interval=3, description=f"zaak for productaanvraag {kenmerk}")


def inbox_productaanvragen(http: requests.Session, zac_url: str, productaanvraagtype: str) -> list[JsonObject]:
    """Return the entries of ZAC's Inbox productaanvragen of the productaanvraagtype."""
    body = {"type": productaanvraagtype, "page": 0, "maxResults": 100}
    response = http.put(f"{zac_url}/rest/inbox-productaanvragen", json=body)
    return entries(cast("JsonObject", expect_status(response, HTTPStatus.OK).json()).get("resultaten"))


def clean_up_inbox_entries(
    http: requests.Session, zac_url: str, registry: ResourceRegistry, productaanvraagtype: str
) -> None:
    """Delete, at cleanup, the entries of ZAC's Inbox productaanvragen of the productaanvraagtype."""

    def delete() -> None:
        for entry in inbox_productaanvragen(http, zac_url, productaanvraagtype):
            expect_status(http.delete(f"{zac_url}/rest/inbox-productaanvragen/{entry['id']}"), HTTPStatus.NO_CONTENT)

    registry.add(f"Inbox productaanvragen of type {productaanvraagtype}", delete)


# ZAC's log line at the end of a reindex of zaken (ReindexSupportService.finishReindex).
REINDEXED = re.compile(r"\[ZAAK\] Reindexing (finished|aborted)")


def reindex_zaken(env: Environment) -> None:
    """Rebuild ZAC's search index of zaken from Open Zaak, through ZAC's internal endpoint; return once it ends.

    Called inside the ZAC pod with the key from its own environment, as ZAC's signaleringen
    CronJob does: the reindex outlasts an ingress timeout. ZAC first empties the index, so its
    search misses zaken until the reindex ends. ZAC 5.9 reindexes in the background (202) and logs its end.
    """
    deployment = env.deployment_for("zac")
    started = time.monotonic()
    url = f"{IN_POD}/rest/internal/indexeren/herindexeren/ZAAK"
    command = f'curl -sS -f -o /dev/null -w "%{{http_code}}" -H "X-API-KEY: $ZAC_INTERNAL_ENDPOINTS_API_KEY" {url}'
    status = env.kube.exec(deployment, "sh", "-c", command, timeout=REINDEX_TIMEOUT)
    if status.strip() != str(HTTPStatus.ACCEPTED.value):
        return

    def has_ended() -> bool:
        since = f"{int(time.monotonic() - started) + 1}s"
        return REINDEXED.search(env.kube.logs(deployment, since=since)) is not None

    wait_until(has_ended, timeout=REINDEX_TIMEOUT, interval=5, description=f"ZAC's reindex of zaken ({deployment})")


def notificatie(kanaal: str, resource: str, url: str, actie: str, **kenmerken: object) -> JsonObject:
    """Return the notificatie Open Notificaties delivers for the resource (url) and actie."""
    return {
        "kanaal": kanaal,
        "hoofdObject": url,
        "resource": resource,
        "resourceUrl": url,
        "actie": actie,
        # ZAC reads microseconds and a zone.
        "aanmaakdatum": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "kenmerken": kenmerken,
    }


def deliver_notificatie(env: Environment, message: JsonObject, times: int) -> list[int]:
    """Deliver the notificatie to ZAC this many times at once, as Open Notificaties does; ZAC's HTTP statuses.

    Sent inside the ZAC pod with ZAC's own key for Open Notificaties; ZAC handles it before it answers.
    """
    post = (
        f"curl -sS -o /dev/null -w '%{{http_code}}\\n' -X POST -H 'Content-Type: application/json'"
        f' -H "Authorization: $OPEN_NOTIFICATIONS_API_SECRET_KEY" --data "$1" {IN_POD}/rest/notificaties'
    )
    command = f"for i in {' '.join(map(str, range(times)))}; do {post} & done; wait"
    output = env.kube.exec(env.deployment_for("zac"), "sh", "-c", command, "sh", json.dumps(message))
    return [int(line) for line in output.split()]


def search(http: requests.Session, zac_url: str, **query: object) -> JsonObject:
    """Return page 1 of ZAC's search (rows 10 unless given) with these RestZoekParameters, as the session's user."""
    body = {"page": 0, "rows": 10, **query}
    return cast("JsonObject", expect_status(http.put(f"{zac_url}/rest/zoeken/list", json=body), HTTPStatus.OK).json())


def search_all(http: requests.Session, zac_url: str, rows: int, **query: object) -> list[JsonObject]:
    """Return every result of ZAC's search with these RestZoekParameters, read page by page of rows."""
    found = search(http, zac_url, rows=rows, **query)
    results = entries(found["resultaten"])
    for page in range(1, -(-int(str(found["totaal"])) // rows)):
        results.extend(entries(search(http, zac_url, page=page, rows=rows, **query)["resultaten"]))
    return results


def csv_export_lines(http: requests.Session, zac_url: str, **query: object) -> list[list[str]]:
    """Return the header and rows of ZAC's CSV export of page 1 of the search with these RestZoekParameters."""
    body = {"page": 0, "rows": 10, **query}
    response = expect_status(http.post(f"{zac_url}/rest/csv/export", json=body), HTTPStatus.OK)
    return list(csv.reader(io.StringIO(response.text), delimiter=";"))


def csv_export(http: requests.Session, zac_url: str, **query: object) -> list[dict[str, str]]:
    """Return the rows of ZAC's CSV export of page 1 of the search with these RestZoekParameters, by column.

    ZAC 5.9.1's header repeats column names after the last column (CsvService.exportToCsv); those hold no values.
    """
    header, *rows = csv_export_lines(http, zac_url, **query)
    return [dict(zip(header, row, strict=False)) for row in rows]


ZOEKOPDRACHT = "/rest/gebruikersvoorkeuren/zoekopdracht"


def zoekopdrachten(http: requests.Session, zac_url: str, werklijst: str) -> list[JsonObject]:
    """Return the user's saved zoekopdrachten of the werklijst (WERKVOORRAAD_ZAKEN, ...)."""
    return get_entries(http, f"{zac_url}{ZOEKOPDRACHT}/{werklijst}")


def save_zoekopdracht(
    http: requests.Session, zac_url: str, registry: ResourceRegistry, werklijst: str, query: JsonObject
) -> JsonObject:
    """Save the werklijst's search (query, as ZAC's UI stores it) under a run-tagged naam; cleanup deletes it."""
    body = {
        "lijstID": werklijst,
        "naam": registry.tagged(f"zoekopdracht-{secrets.token_hex(3)}"),
        "json": json.dumps(query),
    }
    response = expect_status(http.post(zac_url + ZOEKOPDRACHT, json=body), HTTPStatus.OK)
    saved = cast("JsonObject", response.json())
    registry.add(f"zoekopdracht {body['naam']}", lambda: delete_zoekopdracht(http, zac_url, saved))
    return saved


def delete_zoekopdracht(http: requests.Session, zac_url: str, zoekopdracht: JsonObject) -> None:
    """Delete the saved zoekopdracht; ZAC answers 204 also when it is gone."""
    expect_status(http.delete(f"{zac_url}{ZOEKOPDRACHT}/{zoekopdracht['id']}"), HTTPStatus.NO_CONTENT)


def zaaktype_filter(zaaktype_omschrijving: str) -> JsonObject:
    """ZAC's search filter on zaken of the zaaktype."""
    return {"ZAAKTYPE": {"values": [zaaktype_omschrijving]}}


def zaak_zoekresultaat(http: requests.Session, zac_url: str, zaak: JsonObject, **flags: bool) -> JsonObject | None:
    """Return the zaak as ZAC's search for zaken lists it, or None; flags are its alleen* filters.

    Matched by uuid: ZAC's index can hold deleted zaken whose identificatie Open Zaak gave out again (open-zaak-1).
    """
    found = search(http, zac_url, type="ZAAK", zoeken={"ZAAK_IDENTIFICATIE": zaak["identificatie"]}, **flags)
    matches = (item for item in entries(found["resultaten"]) if item.get("id") == zaak["uuid"])
    return next(matches, None)


def is_zaak_listed(http: requests.Session, zac_url: str, zaak: JsonObject, **flags: bool) -> bool:
    """ZAC's search for zaken lists the zaak; flags are its alleen* filters (alleenOpenstaandeZaken: werkvoorraad)."""
    return zaak_zoekresultaat(http, zac_url, zaak, **flags) is not None


def is_taak_listed(http: requests.Session, zac_url: str, taak: JsonObject, **flags: bool) -> bool:
    """ZAC's search for taken lists the taak; flags are its alleen* filters (alleenMijnTaken: Mijn taken).

    Matched by id: ZAC's index can hold taken of deleted zaken whose identificatie Open Zaak gave out again.
    """
    found = search(http, zac_url, type="TAAK", zoeken={"TAAK_ZAAK_ID": taak["zaakIdentificatie"]}, **flags)
    return any(item.get("id") == taak["id"] for item in entries(found["resultaten"]))


def is_document_listed(http: requests.Session, zac_url: str, document: JsonObject) -> bool:
    """ZAC's search for documents lists the document, found by its titel."""
    found = search(http, zac_url, type="DOCUMENT", zoeken={"DOCUMENT_TITEL": document["titel"]})
    return any(item.get("id") == document["uuid"] for item in entries(found["resultaten"]))


def wait_in_werkvoorraad(http: requests.Session, zac_url: str, zaak: JsonObject) -> None:
    """Wait until ZAC's werkvoorraad (its open zaken) lists the zaak."""
    wait_until(
        lambda: is_zaak_listed(http, zac_url, zaak, alleenOpenstaandeZaken=True),
        timeout=INDEX_TIMEOUT,
        description=f"zaak {zaak['identificatie']} in the werkvoorraad",
    )


def wait_for_indicatie(http: requests.Session, zac_url: str, zaak: JsonObject, indicatie: str) -> None:
    """Wait until ZAC's werkvoorraad lists the zaak with the indicatie (OPSCHORTING, HEROPEND, DEELZAAK, ...)."""

    def is_shown() -> bool:
        found = zaak_zoekresultaat(http, zac_url, zaak, alleenOpenstaandeZaken=True)
        return found is not None and indicatie in strings(found.get("indicaties"))

    description = f"zaak {zaak['identificatie']} {indicatie} in the werkvoorraad"
    wait_until(is_shown, timeout=INDEX_TIMEOUT, description=description)


def count_zaken_found(zac: requests.Session, zac_url: str, zaaktype_omschrijving: str) -> int:
    """How many zaken of the zaaktype ZAC's search shows the session's user."""
    found = search(zac, zac_url, rows=1, type="ZAAK", filters=zaaktype_filter(zaaktype_omschrijving))
    return int(str(found["totaal"]))


def toekennen(
    http: requests.Session, zac_url: str, zaak: JsonObject, groep: str, behandelaar: str | None
) -> requests.Response:
    """Assign the zaak to the group and behandelaar, as from the zaak; ZAC's answer."""
    body = {
        "zaakUUID": zaak["uuid"],
        "groepId": groep,
        "behandelaarGebruikersnaam": behandelaar,
        "reden": "podiumd-tests",
    }
    return http.patch(f"{zac_url}/rest/zaken/toekennen", json=body)


# A zaak's streefdatum and fatale datum, which opschorten and verlengen move.
DUE_DATES = ("einddatumGepland", "uiterlijkeEinddatumAfdoening")


def opschorten(
    http: requests.Session, zac_url: str, zaak: JsonObject, days: int, reden: str | None = "podiumd-tests"
) -> requests.Response:
    """Suspend the zaak for the days with the reden (None: none); ZAC's answer."""
    body = {"reason": reden, "numberOfDays": days}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/suspend", json=body)


def hervatten(
    http: requests.Session, zac_url: str, zaak: JsonObject, reden: str | None = "podiumd-tests"
) -> requests.Response:
    """Resume the suspended zaak with the reden (None: none); ZAC's answer."""
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/resume", json={"reason": reden})


def moved_dates(zaak: JsonObject, days: int) -> dict[str, str]:
    """Return those of the streefdatum and fatale datum the zaak has, as ZAC shows the zaak, moved by the days."""
    return {
        field: (date.fromisoformat(str(zaak[field])) + timedelta(days=days)).isoformat()
        for field in DUE_DATES
        if zaak.get(field)
    }


def verlengen(
    http: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    days: int,
    reden: str | None = "podiumd-tests",
    **fields: object,
) -> requests.Response:
    """Extend the zaak by the days from its dates as ZAC shows them, with the reden (None: none); ZAC's answer.

    fields: more of RestZaakVerlengGegevens, such as takenVerlengen to move the fatale datum of its open taken too.
    """
    body = {"redenVerlenging": reden, "duurDagen": days, "takenVerlengen": False, **moved_dates(zaak, days), **fields}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/verlenging", json=body)


# The statustype omschrijving heropenen sets; ZAC answers 500 for a zaaktype without it.
HEROPEND = "Heropend"


def heropenen(http: requests.Session, zac_url: str, zaak: JsonObject) -> requests.Response:
    """Reopen the closed zaak with a reden; ZAC's answer."""
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/heropenen", json={"reden": "podiumd-tests"})
