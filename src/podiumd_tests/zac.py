"""ZAC's REST API without a browser, and its zaakafhandelparameters."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject


def zac_session(env: Environment, username: str, password: str) -> requests.Session:
    """A session on ZAC's REST API, logged in through Keycloak's form."""
    http = env.session()
    form_login(http, env.profile.urls["zac"] + "/", username, password)
    return http


def zaakafhandelparameters(http: requests.Session, zac_url: str, identificatie: str) -> list[JsonObject]:
    """ZAC's zaakafhandelparameters of every version of the zaaktype."""
    found = entries(expect_status(http.get(f"{zac_url}/rest/zaakafhandelparameters"), HTTPStatus.OK).json())
    return [p for p in found if section(p, "zaaktype").get("identificatie") == identificatie]


def confirmation_sent(confirmation: JsonObject) -> bool:
    """ZAC sends this automaticEmailConfirmation: enabled, with a template and a sender."""
    return bool(confirmation.get("enabled") and confirmation.get("templateName") and confirmation.get("emailSender"))


def confirmation_on(http: requests.Session, zac_url: str, identificatie: str) -> bool:
    """ZAC sends its ontvangstbevestiging for productaanvragen of every version of the zaaktype."""
    found = zaakafhandelparameters(http, zac_url, identificatie)
    return bool(found) and all(confirmation_sent(section(p, "automaticEmailConfirmation")) for p in found)


def create_zaak(http: requests.Session, zac_url: str, parameters: JsonObject, **fields: object) -> JsonObject:
    """A zaak started in ZAC, of the zaaktype of these zaakafhandelparameters, in their default group."""
    groep = {"id": parameters["defaultGroepId"], "naam": str(parameters["defaultGroepId"])}
    body = {"zaak": {"zaaktype": parameters["zaaktype"], "groep": groep, **fields}}
    return cast("JsonObject", expect_status(http.post(f"{zac_url}/rest/zaken/zaak", json=body), HTTPStatus.OK).json())


def read_zaak(http: requests.Session, zac_url: str, uuid: str) -> JsonObject:
    """ZAC's view of a zaak."""
    return cast("JsonObject", expect_status(http.get(f"{zac_url}/rest/zaken/zaak/{uuid}"), HTTPStatus.OK).json())


def person_key(http: requests.Session, zac_url: str, bsn: str) -> str:
    """ZAC's temporaryPersonId for a BSN, from its person lookup; ZAC's API takes it instead of the BSN."""
    found = cast(
        "JsonObject", expect_status(http.put(f"{zac_url}/rest/klanten/personen", json={"bsn": bsn}), 200).json()
    )
    return str(entries(found["resultaten"])[0]["temporaryPersonId"])
