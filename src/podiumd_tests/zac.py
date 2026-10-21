"""ZAC's REST API without a browser, and its zaakafhandelparameters."""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.oidc import LOGIN_PATHS
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# ZAC reindexes in the request, page by page; tens of thousands of zaken take minutes.
REINDEX_TIMEOUT = 1800
# Objecten notifies, Open Notificaties delivers to ZAC, and ZAC starts the zaak and its case.
PRODUCTAANVRAAG_TIMEOUT = 120


def zac_session(env: Environment, username: str, password: str) -> requests.Session:
    """A session on ZAC's REST API, logged in through Keycloak's form."""
    http = env.session()
    form_login(http, env.profile.urls["zac"] + LOGIN_PATHS["zac"], username, password)
    return http


def user_groups(http: requests.Session, zac_url: str) -> list[str]:
    """The ids of the groups ZAC knows the session's user in."""
    user = expect_status(http.get(f"{zac_url}/rest/identity/loggedInUser"), HTTPStatus.OK).json()
    return [str(g) for g in user["groupIds"]]


def zaakafhandelparameters(http: requests.Session, zac_url: str, identificatie: str | None = None) -> list[JsonObject]:
    """ZAC's zaakafhandelparameters of every version of the zaaktype, or of every zaaktype ZAC handles.

    ZAC also lists its catalogus' zaaktypen without zaakafhandelparameters, with id null; those are left out.
    """
    found = get_entries(http, f"{zac_url}/rest/zaakafhandelparameters")
    return [
        p
        for p in found
        if p.get("id") is not None and identificatie in {None, section(p, "zaaktype").get("identificatie")}
    ]


# Fields of ZAC's inrichtingscheck that its verdict valide does not require.
NOT_REQUIRED_FOR_VALIDE = {
    "valide",
    "heeftWaarschuwingen",
    "besluittypeAanwezig",
    "isZaakspecifiekeAutorisatieEigenschapAanwezig",
    "isZaakspecifiekeAutorisatieRoltypeAanwezig",
}


def inrichtingscheck_problems(check: JsonObject) -> list[str]:
    """The fields of ZAC's inrichtingscheck of one zaaktype that make it invalid, and its warnings."""
    problems = [k for k, v in check.items() if v is False and k not in NOT_REQUIRED_FOR_VALIDE]
    problems += [f"{k}={v}" for k, v in check.items() if k.startswith("aantal") and v != 1]
    if check.get("resultaattypesMetVerplichtBesluit") and not check.get("besluittypeAanwezig"):
        problems.append("besluittypeAanwezig")
    if check.get("heeftWaarschuwingen"):
        problems.append("heeftWaarschuwingen")
    if not problems and not check.get("valide"):
        problems.append("valide")
    return sorted(problems)


def confirmation_sent(confirmation: JsonObject) -> bool:
    """ZAC sends this automaticEmailConfirmation: enabled, with a template and a sender."""
    return bool(confirmation.get("enabled") and confirmation.get("templateName") and confirmation.get("emailSender"))


def confirmation_on(http: requests.Session, zac_url: str, identificatie: str) -> bool:
    """ZAC sends its ontvangstbevestiging for productaanvragen of every version of the zaaktype."""
    found = zaakafhandelparameters(http, zac_url, identificatie)
    return bool(found) and all(confirmation_sent(section(p, "automaticEmailConfirmation")) for p in found)


def zaak_body(parameters: JsonObject, **fields: object) -> JsonObject:
    """ZAC's request to start a zaak of the zaaktype of these zaakafhandelparameters, in their default group.

    With a startdatum (today unless given) and communicatiekanaal, as ZAC's UI always sends them.
    """
    groep = {"id": parameters["defaultGroepId"], "naam": str(parameters["defaultGroepId"])}
    defaults = {"startdatum": date.today().isoformat(), "communicatiekanaal": "E-mail"}  # noqa: DTZ011  # a local date
    return {"zaak": {"zaaktype": parameters["zaaktype"], "groep": groep, **defaults, **fields}}


def create_zaak(http: requests.Session, zac_url: str, parameters: JsonObject, **fields: object) -> JsonObject:
    """A zaak started in ZAC (zaak_body), as ZAC shows it."""
    response = http.post(f"{zac_url}/rest/zaken/zaak", json=zaak_body(parameters, **fields))
    created = cast("JsonObject", expect_status(response, HTTPStatus.OK).json())
    if "uuid" in created:
        return created
    # ZAC 5.9 answers only the identificatie.
    found = http.get(f"{zac_url}/rest/zaken/zaak/id/{created['identificatie']}")
    return cast("JsonObject", expect_status(found, HTTPStatus.OK).json())


def read_zaak(http: requests.Session, zac_url: str, uuid: str) -> JsonObject:
    """ZAC's view of a zaak."""
    return cast("JsonObject", expect_status(http.get(f"{zac_url}/rest/zaken/zaak/{uuid}"), HTTPStatus.OK).json())


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


def productaanvraag_zaak(
    openzaak: ApiClient, registry: ResourceRegistry, kenmerk: str, timeout: float = PRODUCTAANVRAAG_TIMEOUT
) -> JsonObject:
    """The zaak ZAC starts for a productaanvraag, with its kenmerk in the toelichting; cleanup deletes it.

    openzaak: a client that may read and delete zaken of the zaaktype (bootstrap openzaak-client-productaanvraag).
    """

    # ZAC dates the zaak in Dutch time: around midnight a day after the UTC date.
    since = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()

    def started() -> JsonObject | None:
        zaken = openzaak.list(f"{ZAKEN}/zaken", {"startdatum__gte": since})
        return next((z for z in zaken if kenmerk in str(z.get("toelichting") or "")), None)

    def delete() -> None:
        zaak = started()
        if zaak:
            delete_zaak(openzaak, str(zaak["url"]), with_documents=True)

    # Registered before the wait, so a zaak started after a timeout goes too.
    registry.add(f"zaak for productaanvraag {kenmerk}", delete)
    return wait_until(started, timeout=timeout, interval=3, description=f"zaak for productaanvraag {kenmerk}")


def reindex_zaken(env: Environment) -> None:
    """Rebuild ZAC's search index of zaken from Open Zaak, through ZAC's internal endpoint.

    Called inside the ZAC pod with the key from its own environment, as ZAC's signaleringen
    CronJob does: the reindex outlasts an ingress timeout. ZAC first empties the index, so its
    search misses zaken until the call returns.
    """
    url = "http://localhost:8080/rest/internal/indexeren/herindexeren/ZAAK"
    command = f'curl -sS -f -o /dev/null -H "X-API-KEY: $ZAC_INTERNAL_ENDPOINTS_API_KEY" {url}'
    env.kube.exec(env.deployment_for("zac"), "sh", "-c", command, timeout=REINDEX_TIMEOUT)


def search(http: requests.Session, zac_url: str, **query: object) -> JsonObject:
    """The first page of ZAC's search (rows 10 unless given) with these RestZoekParameters, as the session's user."""
    body = {"page": 0, "rows": 10, **query}
    return cast("JsonObject", expect_status(http.put(zac_url + "/rest/zoeken/list", json=body), HTTPStatus.OK).json())


def zaak_listed(http: requests.Session, zac_url: str, identificatie: str, **flags: bool) -> bool:
    """ZAC's search for zaken lists the zaak; flags are its alleen* filters (alleenOpenstaandeZaken: werkvoorraad)."""
    found = search(http, zac_url, type="ZAAK", zoeken={"ZAAK_IDENTIFICATIE": identificatie}, **flags)
    return any(r.get("identificatie") == identificatie for r in entries(found["resultaten"]))


def count_zaken_found(zac: requests.Session, zac_url: str, zaaktype_omschrijving: str) -> int:
    """How many zaken of the zaaktype ZAC's search shows the session's user."""
    found = search(zac, zac_url, rows=1, type="ZAAK", filters={"ZAAKTYPE": {"values": [zaaktype_omschrijving]}})
    return int(str(found["totaal"]))
