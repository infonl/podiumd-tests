"""ZAC's beheer of referentietabellen."""

from __future__ import annotations

import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    import requests

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

REFERENTIETABELLEN = "/rest/referentietabellen"
# RestReferenceTableValue.REFERENCE_TABLE_VALUE_MAX_LENGTH.
VALUE_MAX_LENGTH = 1000


def referentietabel(http: requests.Session, zac_url: str, code: str) -> JsonObject:
    """ZAC's referentietabel with this code, with its values."""
    response = http.get(f"{zac_url}{REFERENTIETABELLEN}/code/{code}")
    return cast("JsonObject", expect_status(response, HTTPStatus.OK).json())


def referentietabel_values(tabel: JsonObject) -> list[str]:
    """Return the names of the referentietabel's values, in ZAC's order."""
    return [str(value["name"]) for value in entries(tabel.get("values"))]


def has_same_values(tabel: JsonObject, other: JsonObject) -> bool:
    """Whether the referentietabellen hold the same values; ZAC 5.9.1 reads them in no fixed order."""
    return sorted(referentietabel_values(tabel)) == sorted(referentietabel_values(other))


def create_referentietabel(
    http: requests.Session, zac_url: str, registry: ResourceRegistry, values: list[str]
) -> JsonObject:
    """Create a referentietabel with a run-tagged code and name and these values; cleanup deletes it."""
    code = registry.tagged(f"zac-{secrets.token_hex(3)}").upper()
    body = {"code": code, "name": code, "values": [{"name": value} for value in values]}
    response = http.post(zac_url + REFERENTIETABELLEN, json=body)
    created = cast("JsonObject", expect_status(response, HTTPStatus.OK).json())

    def delete() -> None:
        # A test may have deleted it: ZAC answers 404.
        expect_status(delete_referentietabel(http, zac_url, created), HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND)

    registry.add(f"ZAC referentietabel {code}", delete)
    return created


def update_referentietabel(
    http: requests.Session, zac_url: str, tabel: JsonObject, values: Sequence[Mapping[str, object]]
) -> requests.Response:
    """Save the referentietabel with these values (name, systemValue; id of an existing one); ZAC's answer."""
    body = {"name": tabel["name"], "code": tabel["code"], "values": values}
    return http.put(f"{zac_url}{REFERENTIETABELLEN}/{tabel['id']}", json=body)


def delete_referentietabel(http: requests.Session, zac_url: str, tabel: JsonObject) -> requests.Response:
    """Delete the referentietabel; ZAC's answer."""
    return http.delete(f"{zac_url}{REFERENTIETABELLEN}/{tabel['id']}")


def guard_referentietabel(http: requests.Session, zac_url: str, registry: ResourceRegistry, tabel: JsonObject) -> None:
    """At cleanup, save the referentietabel (as read, with its values) back when its values differ then.

    For a request ZAC should refuse on an estate's table: a regression must not leave the table changed.
    """

    def restore() -> None:
        current = referentietabel(http, zac_url, str(tabel["code"]))
        if has_same_values(current, tabel):
            return
        ids = {value["name"]: value["id"] for value in entries(current.get("values"))}
        before = entries(tabel.get("values"))
        values = [{**value, "id": ids.get(value["name"])} for value in before]
        expect_status(update_referentietabel(http, zac_url, tabel, values), HTTPStatus.OK)

    registry.add(f"ZAC referentietabel {tabel['code']} as before", restore)
