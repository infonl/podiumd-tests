"""ZAC's REST API without a browser, and its zaakafhandelparameters."""

from __future__ import annotations

from datetime import date
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
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

# Objecten notifies, Open Notificaties delivers to ZAC, and ZAC starts the zaak and its case.
PRODUCTAANVRAAG_TIMEOUT = 120


def zac_session(env: Environment, username: str, password: str) -> requests.Session:
    """A session on ZAC's REST API, logged in through Keycloak's form."""
    http = env.session()
    form_login(http, env.profile.urls["zac"] + "/", username, password)
    return http


def zaakafhandelparameters(http: requests.Session, zac_url: str, identificatie: str | None = None) -> list[JsonObject]:
    """ZAC's zaakafhandelparameters of every version of the zaaktype, or of every zaaktype ZAC handles."""
    found = entries(expect_status(http.get(f"{zac_url}/rest/zaakafhandelparameters"), HTTPStatus.OK).json())
    return [p for p in found if identificatie in {None, section(p, "zaaktype").get("identificatie")}]


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
    """A zaak started in ZAC (zaak_body)."""
    response = http.post(f"{zac_url}/rest/zaken/zaak", json=zaak_body(parameters, **fields))
    return cast("JsonObject", expect_status(response, HTTPStatus.OK).json())


def read_zaak(http: requests.Session, zac_url: str, uuid: str) -> JsonObject:
    """ZAC's view of a zaak."""
    return cast("JsonObject", expect_status(http.get(f"{zac_url}/rest/zaken/zaak/{uuid}"), HTTPStatus.OK).json())


def person_key(http: requests.Session, zac_url: str, bsn: str) -> str:
    """ZAC's temporaryPersonId for a BSN, from its person lookup; ZAC's API takes it instead of the BSN."""
    found = cast(
        "JsonObject", expect_status(http.put(f"{zac_url}/rest/klanten/personen", json={"bsn": bsn}), 200).json()
    )
    return str(entries(found["resultaten"])[0]["temporaryPersonId"])


def send_with_person(
    http: requests.Session, zac_url: str, bsn: str, send: Callable[[JsonObject], requests.Response]
) -> requests.Response:
    """send(the person's BetrokkeneIdentificatie); once more with a fresh lookup when ZAC answers 410.

    ZAC 5.4.5 keeps handing out a temporaryPersonId it forgot 12 h after its last read (PLAN §13);
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

    def started() -> JsonObject | None:
        zaken = openzaak.list(f"{ZAKEN}/zaken", {"startdatum": today()})
        return next((z for z in zaken if kenmerk in str(z.get("toelichting") or "")), None)

    zaak = wait_until(started, timeout=timeout, interval=3, description=f"zaak for productaanvraag {kenmerk}")
    url = str(zaak["url"])
    registry.add(f"zaak {url}", lambda: delete_zaak(openzaak, url, with_documents=True))
    return zaak
