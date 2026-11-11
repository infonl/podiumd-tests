"""ZAC's REST API without a browser, and its zaakafhandelparameters."""

from __future__ import annotations

import json

from datetime import date
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
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openzaak import ZAKEN
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

# ZAC's own address inside its pod.
IN_POD = "http://localhost:8080"
# ZAC reindexes in the request, page by page; tens of thousands of zaken take minutes.
REINDEX_TIMEOUT = 1800
# Objecten notifies, Open Notificaties delivers to ZAC, and ZAC starts the zaak and its case.
PRODUCTAANVRAAG_TIMEOUT = 120
# ZAC indexes a zaak in Solr after Open Notificaties tells it about the change.
INDEX_TIMEOUT = 60
# Open Notificaties delivers a catalogus change to ZAC.
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


def user_groups(http: requests.Session, zac_url: str) -> list[str]:
    """Return the ids of the groups ZAC knows the session's user in."""
    user = expect_status(http.get(f"{zac_url}/rest/identity/loggedInUser"), HTTPStatus.OK).json()
    return [str(group) for group in user["groupIds"]]


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
    response = http.put(f"{zac_url}/rest/zaakafhandelparameters", json=parameters)
    return cast("JsonObject", expect_status(response, HTTPStatus.OK).json())


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


def behandelaar_groups(http: requests.Session, zac_url: str, omschrijving: str) -> set[str]:
    """Return the ids of the groups ZAC offers as behandelaar of zaken of the zaaktype: those PABC authorises."""
    url = f"{zac_url}/rest/identity/zaaktype/{omschrijving}/behandelaar-groups"
    return {str(group["id"]) for group in get_entries(http, url)}


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


def is_confirmation_sent(confirmation: JsonObject) -> bool:
    """ZAC sends this automaticEmailConfirmation: enabled, with a template and a sender."""
    return bool(confirmation.get("enabled") and confirmation.get("templateName") and confirmation.get("emailSender"))


def is_confirmation_on(http: requests.Session, zac_url: str, identificatie: str) -> bool:
    """ZAC sends its ontvangstbevestiging for productaanvragen of every version of the zaaktype."""
    found = zaakafhandelparameters(http, zac_url, identificatie)
    return bool(found) and all(
        is_confirmation_sent(section(parameters, "automaticEmailConfirmation")) for parameters in found
    )


# The reason ZAC always offers for aborting a zaak.
NIET_ONTVANKELIJK = "ZAAK_NIET_ONTVANKELIJK"


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


def read_zaak(http: requests.Session, zac_url: str, uuid: str) -> JsonObject:
    """ZAC's view of a zaak."""
    return cast("JsonObject", expect_status(http.get(f"{zac_url}/rest/zaken/zaak/{uuid}"), HTTPStatus.OK).json())


def zaak_historie(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return ZAC's historie of the zaak, newest first."""
    return get_entries(http, f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/historie")


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


def afhandelen(http: requests.Session, zac_url: str, zaak: JsonObject) -> requests.Response:
    """Run ZAAK_AFHANDELEN of a CMMN zaak with a resultaattype that needs no besluit; ZAC's answer."""
    resultaattype = _resultaattype_without_besluit(http, zac_url, zaak)
    fields = {"resultaattypeUuid": resultaattype, "resultaatToelichting": "podiumd-tests"}
    return user_event(http, zac_url, str(zaak["uuid"]), "ZAAK_AFHANDELEN", **fields)


def afbreken(http: requests.Session, zac_url: str, zaak: JsonObject) -> requests.Response:
    """Abort the zaak as niet ontvankelijk; ZAC's answer."""
    body = {"zaakbeeindigRedenId": NIET_ONTVANKELIJK}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/afbreken", json=body)


def afsluiten(http: requests.Session, zac_url: str, zaak: JsonObject) -> requests.Response:
    """Close the zaak with a resultaattype that needs no besluit, as for a BPMN zaak; ZAC's answer."""
    body = {"reden": "podiumd-tests", "resultaattypeUuid": _resultaattype_without_besluit(http, zac_url, zaak)}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/afsluiten", json=body)


def wijzig_zaak(http: requests.Session, zac_url: str, zaak: JsonObject, **fields: object) -> requests.Response:
    """Change these fields (RestZaakCreateData) of the zaak, with a reden; ZAC's answer."""
    data = {"omschrijving": zaak["omschrijving"], "zaaktype": zaak["zaaktype"], **fields}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}", json={"zaak": data, "reden": "podiumd-tests"})


def assignment(item: JsonObject) -> tuple[object, object]:
    """(group id, behandelaar id) of ZAC's view of a zaak or task."""
    return section(item, "groep").get("id"), section(item, "behandelaar").get("id")


def verdelen(
    http: requests.Session, zac_url: str, uuids: list[str], groep: str, behandelaar: str | None
) -> requests.Response:
    """Assign the zaken from the werkvoorraad to the group and behandelaar; ZAC's answer, before its background job."""
    body = {"uuids": uuids, "groepId": groep, "behandelaarGebruikersnaam": behandelaar, "reden": "podiumd-tests"}
    return http.put(f"{zac_url}/rest/zaken/lijst/verdelen", json=body)


def vrijgeven(http: requests.Session, zac_url: str, uuids: list[str]) -> requests.Response:
    """Release the zaken from the werkvoorraad; ZAC's answer, before its background job."""
    return http.put(f"{zac_url}/rest/zaken/lijst/vrijgeven", json={"uuids": uuids, "reden": "podiumd-tests"})


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


def afzenders(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the afzenders ZAC offers for mail from the zaak."""
    return get_entries(http, f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/afzender")


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


def productaanvraag_zaken(openzaak: ApiClient, kenmerk: str) -> list[JsonObject]:
    """Return the zaken started since yesterday with the productaanvraag's kenmerk in the toelichting."""
    # ZAC dates the zaak in Dutch time: around midnight a day after the UTC date.
    since = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
    zaken = openzaak.list(f"{ZAKEN}/zaken", {"startdatum__gte": since})
    return [zaak for zaak in zaken if kenmerk in str(zaak.get("toelichting") or "")]


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


def reindex_zaken(env: Environment) -> None:
    """Rebuild ZAC's search index of zaken from Open Zaak, through ZAC's internal endpoint.

    Called inside the ZAC pod with the key from its own environment, as ZAC's signaleringen
    CronJob does: the reindex outlasts an ingress timeout. ZAC first empties the index, so its
    search misses zaken until the call returns.
    """
    url = f"{IN_POD}/rest/internal/indexeren/herindexeren/ZAAK"
    command = f'curl -sS -f -o /dev/null -H "X-API-KEY: $ZAC_INTERNAL_ENDPOINTS_API_KEY" {url}'
    env.kube.exec(env.deployment_for("zac"), "sh", "-c", command, timeout=REINDEX_TIMEOUT)


def deliver_notificatie(env: Environment, notificatie: JsonObject, times: int) -> list[int]:
    """Deliver the notificatie to ZAC this many times at once, as Open Notificaties does; ZAC's HTTP statuses.

    Sent inside the ZAC pod with ZAC's own key for Open Notificaties; ZAC handles it before it answers.
    """
    post = (
        f"curl -sS -o /dev/null -w '%{{http_code}}\\n' -X POST -H 'Content-Type: application/json'"
        f' -H "Authorization: $OPEN_NOTIFICATIONS_API_SECRET_KEY" --data "$1" {IN_POD}/rest/notificaties'
    )
    command = f"for i in {' '.join(map(str, range(times)))}; do {post} & done; wait"
    output = env.kube.exec(env.deployment_for("zac"), "sh", "-c", command, "sh", json.dumps(notificatie))
    return [int(line) for line in output.split()]


def search(http: requests.Session, zac_url: str, **query: object) -> JsonObject:
    """Return page 1 of ZAC's search (rows 10 unless given) with these RestZoekParameters, as the session's user."""
    body = {"page": 0, "rows": 10, **query}
    return cast("JsonObject", expect_status(http.put(f"{zac_url}/rest/zoeken/list", json=body), HTTPStatus.OK).json())


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


def open_task(http: requests.Session, zac_url: str, zaak_uuid: str, name: str) -> JsonObject:
    """Wait until the zaak has an open task of this name, as ZAC lists it (with its formioFormulier)."""

    def found() -> JsonObject | None:
        tasks = get_entries(http, f"{zac_url}/rest/taken/zaak/{zaak_uuid}")
        open_tasks = (task for task in tasks if task.get("status") != "AFGEROND")
        return next((task for task in open_tasks if task.get("naam") == name), None)

    return wait_until(found, timeout=TASK_TIMEOUT, description=f"open task {name!r} on zaak {zaak_uuid}")


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


def human_tasks_offered(http: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    """Return the plan items of the human tasks ZAC offers to start on the zaak now."""
    return get_entries(http, f"{zac_url}/rest/planitems/zaak/{zaak['uuid']}/humanTaskPlanItems")


def start_human_task(
    http: requests.Session, zac_url: str, zaak: JsonObject, name: str, groep: str, **fields: object
) -> requests.Response:
    """Start the zaak's human task of this name for the group, once ZAC offers it; ZAC's answer.

    ZAC starts a zaak's case, and the stage after the intake, in the background. fields: more of ZAC's
    RESTHumanTaskData (medewerker, fataledatum, toelichting, taakdata, taakStuurGegevens: no mail unless given).
    """

    def offered() -> JsonObject | None:
        return next((item for item in human_tasks_offered(http, zac_url, zaak) if item.get("naam") == name), None)

    plan_item = wait_until(offered, timeout=INDEX_TIMEOUT, description=f"{name!r} offered on {zaak['identificatie']}")
    body = {
        "planItemInstanceId": plan_item["id"],
        "groep": {"id": groep, "naam": groep},
        "taakdata": {},
        "taakStuurGegevens": {"sendMail": False},
        **fields,
    }
    return http.post(f"{zac_url}/rest/planitems/doHumanTaskPlanItem", json=body)


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
    found = search(zac, zac_url, rows=1, type="ZAAK", filters={"ZAAKTYPE": {"values": [zaaktype_omschrijving]}})
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


def opschorten(
    http: requests.Session, zac_url: str, zaak: JsonObject, days: int, reden: str = "podiumd-tests"
) -> requests.Response:
    """Suspend the zaak for the days with the reden; ZAC's answer."""
    body = {"reason": reden, "numberOfDays": days}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/suspend", json=body)


def verlengen(http: requests.Session, zac_url: str, zaak: JsonObject, days: int) -> requests.Response:
    """Extend the zaak by the days, with its streefdatum and fatale datum as ZAC shows the zaak; ZAC's answer."""
    moved = {
        field: (date.fromisoformat(str(zaak[field])) + timedelta(days=days)).isoformat()
        for field in ("einddatumGepland", "uiterlijkeEinddatumAfdoening")
        if zaak.get(field)
    }
    body = {"redenVerlenging": "podiumd-tests", "duurDagen": days, "takenVerlengen": False, **moved}
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/verlenging", json=body)


# The statustype omschrijving heropenen sets; ZAC answers 500 for a zaaktype without it.
HEROPEND = "Heropend"


def heropenen(http: requests.Session, zac_url: str, zaak: JsonObject) -> requests.Response:
    """Reopen the closed zaak with a reden; ZAC's answer."""
    return http.patch(f"{zac_url}/rest/zaken/zaak/{zaak['uuid']}/heropenen", json={"reden": "podiumd-tests"})
