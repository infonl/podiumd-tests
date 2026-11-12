"""ZAC's signaleringen of the session's user: its settings and its dashboard lists."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.json_data import entries
from podiumd_tests.mailpit import full_message
from podiumd_tests.mailpit import quoted
from podiumd_tests.mailpit import received_mails
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

SETTINGS = "/rest/signaleringen/instellingen"


def signalering_settings(http: requests.Session, zac_url: str) -> list[JsonObject]:
    """Return the user's setting of each signalering type: dashboard and mail on or off."""
    return get_entries(http, zac_url + SETTINGS)


def save_signalering_setting(http: requests.Session, zac_url: str, setting: JsonObject) -> None:
    """Save the user's setting of one signalering type (type, dashboard, mail)."""
    expect_status(http.put(zac_url + SETTINGS, json=setting), HTTPStatus.OK, HTTPStatus.NO_CONTENT)


def turn_signaleringen(
    http: requests.Session, zac_url: str, registry: ResourceRegistry, *, mail: bool = False, **types: bool
) -> None:
    """Turn the user's dashboard signal per type on or off, and mail for those types; cleanup restores them."""
    before = [setting for setting in signalering_settings(http, zac_url) if setting.get("type") in types]
    registry.add(f"ZAC signaleringen {sorted(types)}", lambda: _save_all(http, zac_url, before))
    for soort, on in types.items():
        save_signalering_setting(http, zac_url, {"type": soort, "dashboard": on, "mail": mail})


def mail_group_signalering(
    http: requests.Session, zac_url: str, registry: ResourceRegistry, group: str, soort: str
) -> None:
    """Have ZAC mail the group's signalering of the type, as the beheerder sets it; cleanup turns the mail off.

    ZAC mails the address in the group's Keycloak attribute email.
    """
    url = f"{zac_url}/rest/signaleringen/group/{group}/instellingen"

    def save(*, mail: bool) -> None:
        expect_status(http.put(url, json={"type": soort, "mail": mail}), HTTPStatus.OK, HTTPStatus.NO_CONTENT)

    save(mail=True)
    registry.add(f"ZAC signalering {soort} of group {group}", lambda: save(mail=False))


def _save_all(http: requests.Session, zac_url: str, settings: list[JsonObject]) -> None:
    for setting in settings:
        save_signalering_setting(http, zac_url, setting)


def signalering_zaken(http: requests.Session, zac_url: str, soort: str) -> list[str]:
    """Return the identificaties of the zaken on the user's dashboard list of the type (ZAAK_OP_NAAM, ...).

    ZAC's list has no uuid; it reads each zaak from Open Zaak, so an identificatie there is a live zaak.
    """
    return [str(zaak.get("identificatie")) for zaak in signalering_overzichten(http, zac_url, soort)]


def signalering_overzichten(http: requests.Session, zac_url: str, soort: str) -> list[JsonObject]:
    """Return the zaken on the user's dashboard list of the type, as ZAC shows them."""
    page = {"page": 0, "rows": 100, "sortField": "SIGNALERING_TIJDSTIP", "sortOrder": "DESC"}
    found = expect_status(http.put(f"{zac_url}/rest/signaleringen/zaken/{soort}", json=page), HTTPStatus.OK)
    return entries(found.json().get("resultaten"))


def signalering_taken(http: requests.Session, zac_url: str) -> list[str]:
    """Return the ids of the taken on the user's dashboard list Taak op naam."""
    return [str(taak.get("id")) for taak in get_entries(http, f"{zac_url}/rest/signaleringen/taken/TAAK_OP_NAAM")]


def signalering_mail(
    mailpit: ApiClient, registry: ResourceRegistry, username: str, text: str, *, timeout: float
) -> JsonObject:
    """Wait for a mail to the user's Keycloak address holding the text (a zaaknummer, a taak link); the full message."""
    query = f"to:{quoted(user_email(username))} {quoted(text)}"
    return full_message(mailpit, received_mails(mailpit, registry, query, timeout=timeout)[0])
