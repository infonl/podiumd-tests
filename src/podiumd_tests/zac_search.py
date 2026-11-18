"""ZAC's search: results of zaken, taken and documents, the werklijsten, CSV export and saved zoekopdrachten."""

from __future__ import annotations

import csv
import io
import json
import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import requests

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import strings
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import INDEX_TIMEOUT

if TYPE_CHECKING:
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


def search(http: requests.Session, zac_url: str, **query: object) -> JsonObject:
    """Return page 1 of ZAC's search (rows 10 unless given) with these RestZoekParameters, as the session's user."""
    body = {"page": 0, "rows": 10, **query}
    return cast("JsonObject", expect_status(http.put(f"{zac_url}/rest/zoeken/list", json=body), HTTPStatus.OK).json())


def search_failure(http: requests.Session, zac_url: str) -> str | None:
    """Return why ZAC's search for zaken fails (its status and body, or the exception); None when it answers."""
    try:
        search(http, zac_url, type="ZAAK", rows=1)
    except (UnexpectedStatusError, requests.RequestException) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


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


def _zoekresultaat(
    http: requests.Session, zac_url: str, wanted: str, query: JsonObject, **flags: bool
) -> JsonObject | None:
    """Return the search result with id `wanted` of ZAC's search with this query, or None."""
    found = search(http, zac_url, **query, **flags)
    return next((item for item in entries(found["resultaten"]) if item.get("id") == wanted), None)


def zaak_zoekresultaat(http: requests.Session, zac_url: str, zaak: JsonObject, **flags: bool) -> JsonObject | None:
    """Return the zaak as ZAC's search for zaken lists it, or None; flags are its alleen* filters.

    Matched by uuid: ZAC's index can hold deleted zaken whose identificatie Open Zaak gave out again (open-zaak-1).
    """
    query = {"type": "ZAAK", "zoeken": {"ZAAK_IDENTIFICATIE": zaak["identificatie"]}}
    return _zoekresultaat(http, zac_url, str(zaak["uuid"]), query, **flags)


def is_zaak_listed(http: requests.Session, zac_url: str, zaak: JsonObject, **flags: bool) -> bool:
    """ZAC's search for zaken lists the zaak; flags are its alleen* filters (alleenOpenstaandeZaken: werkvoorraad)."""
    return zaak_zoekresultaat(http, zac_url, zaak, **flags) is not None


def taak_zoekresultaat(http: requests.Session, zac_url: str, taak: JsonObject, **flags: bool) -> JsonObject | None:
    """Return the taak as ZAC's search for taken lists it, or None; flags are its alleen* filters.

    Matched by id: ZAC's index can hold taken of deleted zaken whose identificatie Open Zaak gave out again.
    """
    query = {"type": "TAAK", "zoeken": {"TAAK_ZAAK_ID": taak["zaakIdentificatie"]}}
    return _zoekresultaat(http, zac_url, str(taak["id"]), query, **flags)


def is_taak_listed(http: requests.Session, zac_url: str, taak: JsonObject, **flags: bool) -> bool:
    """ZAC's search for taken lists the taak; flags are its alleen* filters (alleenMijnTaken: Mijn taken)."""
    return taak_zoekresultaat(http, zac_url, taak, **flags) is not None


def document_zoekresultaat(http: requests.Session, zac_url: str, document: JsonObject) -> JsonObject | None:
    """Return the document as ZAC's search for documents lists it, found by its titel, or None."""
    query = {"type": "DOCUMENT", "zoeken": {"DOCUMENT_TITEL": document["titel"]}}
    return _zoekresultaat(http, zac_url, str(document["uuid"]), query)


def is_document_listed(http: requests.Session, zac_url: str, document: JsonObject) -> bool:
    """ZAC's search for documents lists the document, found by its titel."""
    return document_zoekresultaat(http, zac_url, document) is not None


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
