"""ZAC's signaleringen of the session's user: its settings and its dashboard lists."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries

if TYPE_CHECKING:
    import requests

    from podiumd_tests.json_data import JsonObject

SETTINGS = "/rest/signaleringen/instellingen"


def signalering_settings(http: requests.Session, zac_url: str) -> list[JsonObject]:
    """Return the user's setting of each signalering type: dashboard and mail on or off."""
    return get_entries(http, zac_url + SETTINGS)


def save_signalering_setting(http: requests.Session, zac_url: str, setting: JsonObject) -> None:
    """Save the user's setting of one signalering type (type, dashboard, mail)."""
    expect_status(http.put(zac_url + SETTINGS, json=setting), HTTPStatus.OK, HTTPStatus.NO_CONTENT)


def signalering_zaken(http: requests.Session, zac_url: str, soort: str) -> list[str]:
    """Return the identificaties of the zaken on the user's dashboard list of the type (ZAAK_OP_NAAM, ...).

    ZAC's list has no uuid; it reads each zaak from Open Zaak, so an identificatie there is a live zaak.
    """
    page = {"page": 0, "rows": 100, "sortField": "SIGNALERING_TIJDSTIP", "sortOrder": "DESC"}
    found = expect_status(http.put(f"{zac_url}/rest/signaleringen/zaken/{soort}", json=page), HTTPStatus.OK)
    return [str(zaak.get("identificatie")) for zaak in entries(found.json().get("resultaten"))]


def signalering_taken(http: requests.Session, zac_url: str) -> list[str]:
    """Return the ids of the taken on the user's dashboard list Taak op naam."""
    return [str(taak.get("id")) for taak in get_entries(http, f"{zac_url}/rest/signaleringen/taken/TAAK_OP_NAAM")]
