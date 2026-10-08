"""Open Zaak test data through the ZGW APIs; every factory registers its deleter (PLAN.md §4 B)."""

from __future__ import annotations

import base64
import secrets

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.json_data import strings
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

ZAKEN = "zaken/api/v1"
DELETE_TIMEOUT = 30
CATALOGI = "catalogi/api/v1"


def today() -> str:
    """Today's date as the ZGW APIs expect it."""
    return datetime.now(tz=UTC).date().isoformat()


def _create(openzaak: ApiClient, registry: ResourceRegistry, path: str, body: dict[str, object]) -> JsonObject:
    created = openzaak.post(path, body)
    url = str(created["url"])
    registry.add(f"{path} {url}", lambda: openzaak.delete(url))
    return created


def delete_zaak(openzaak: ApiClient, url: str) -> None:
    """DELETE a zaak, retrying until it is gone.

    Open Zaak 1.29.3 answers 500 on deleting a zaak with a resultaat although it deletes it
    (the ETag of the deleted resultaat is recalculated; test_closed_zaak_delete_answers_204
    tracks it). It also answers 500 and keeps the zaak when another client (ZAC) adds a rol
    during the delete. A 500 counts as deleted only when the zaak is gone.
    """

    def deleted() -> bool:
        response = openzaak.request(
            "DELETE", url, HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND, HTTPStatus.INTERNAL_SERVER_ERROR
        )
        if response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
            openzaak.request("GET", url, HTTPStatus.NOT_FOUND)
        return True

    wait_until(deleted, timeout=DELETE_TIMEOUT, description=f"DELETE {url}")


def make_zaak(openzaak: ApiClient, registry: ResourceRegistry, zaaktype: str, **fields: object) -> JsonObject:
    """A zaak of a zaaktype whose omschrijving carries the run tag; fields override the defaults."""
    body: dict[str, object] = {
        "bronorganisatie": TEST_CATALOGUS_RSIN,
        "verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN,
        "zaaktype": zaaktype,
        "startdatum": today(),
        "omschrijving": registry.tagged("zaak"),
        "vertrouwelijkheidaanduiding": "openbaar",
        **fields,
    }
    zaak = openzaak.post(f"{ZAKEN}/zaken", body)
    url = str(zaak["url"])
    registry.add(f"zaak {url}", lambda: delete_zaak(openzaak, url))
    return zaak


DOCUMENTEN = "documenten/api/v1"
BESLUITEN = "besluiten/api/v1"


@dataclass(frozen=True)
class ZaaktypeParts:
    """The types configured on a zaaktype, looked up once."""

    zaaktype: str
    statustypen: list[JsonObject]  # by volgnummer; the last is the eindstatus
    roltypen: dict[str, str]  # omschrijvingGeneriek -> url
    informatieobjecttype: str
    eigenschappen: dict[str, str]  # naam -> url
    besluittype: str
    resultaattypen: list[str]


def zaaktype_parts(openzaak: ApiClient, zaaktype: JsonObject) -> ZaaktypeParts:
    """Look up the statustypen, roltypen, informatieobjecttype, eigenschappen, besluittype and resultaattypen."""
    url = str(zaaktype["url"])
    statustypen = sorted(
        openzaak.list(f"{CATALOGI}/statustypen", {"zaaktype": url}), key=lambda s: int(str(s["volgnummer"]))
    )
    roltypen = {
        str(r["omschrijvingGeneriek"]): str(r["url"]) for r in openzaak.list(f"{CATALOGI}/roltypen", {"zaaktype": url})
    }
    eigenschappen = {
        str(e["naam"]): str(e["url"]) for e in openzaak.list(f"{CATALOGI}/eigenschappen", {"zaaktype": url})
    }
    besluittypen = openzaak.list(f"{CATALOGI}/besluittypen", {"zaaktypen": url})
    resultaattypen = [str(r["url"]) for r in openzaak.list(f"{CATALOGI}/resultaattypen", {"zaaktype": url})]
    iots = strings(zaaktype.get("informatieobjecttypen"))
    return ZaaktypeParts(
        url, statustypen, roltypen, iots[0], eigenschappen, str(besluittypen[0]["url"]), resultaattypen
    )


def make_status(
    openzaak: ApiClient, zaak: JsonObject, statustype: str, toelichting: str = "", gezet: datetime | None = None
) -> JsonObject:
    """A status of a zaak, set now or at gezet; deleted with the zaak."""
    body = {
        "zaak": zaak["url"],
        "statustype": statustype,
        "datumStatusGezet": (gezet or datetime.now(tz=UTC)).isoformat(),
        "statustoelichting": toelichting,
    }
    return openzaak.post(f"{ZAKEN}/statussen", body)


def close_zaak(
    openzaak: ApiClient, zaak: JsonObject, parts: ZaaktypeParts, gezet: datetime | None = None
) -> JsonObject:
    """Close a zaak with the zaaktype's first resultaattype and its eindstatus (at gezet); the closed zaak.

    Open Zaak then sets einddatum, archiefnominatie and archiefactiedatum from the resultaattype.
    """
    body = {"zaak": zaak["url"], "resultaattype": parts.resultaattypen[0], "toelichting": "afgehandeld"}
    openzaak.post(f"{ZAKEN}/resultaten", body)
    make_status(openzaak, zaak, str(parts.statustypen[-1]["url"]), "Afgehandeld", gezet)
    return openzaak.get(str(zaak["url"]))


# The _zoek and list filter for the BSN of a natuurlijk-persoon rol.
BSN_FILTER = "rol__betrokkeneIdentificatie__natuurlijkPersoon__inpBsn"


def make_rol(
    openzaak: ApiClient,
    registry: ResourceRegistry,
    zaak: JsonObject,
    roltype: str,
    betrokkene_type: str = "natuurlijk_persoon",
    **identificatie: object,
) -> JsonObject:
    """A rol on a zaak; identificatie is the betrokkeneIdentificatie (e.g. inpBsn=...)."""
    body: dict[str, object] = {
        "zaak": zaak["url"],
        "betrokkeneType": betrokkene_type,
        "roltype": roltype,
        "roltoelichting": registry.tagged("rol"),
        "betrokkeneIdentificatie": identificatie,
    }
    return _create(openzaak, registry, f"{ZAKEN}/rollen", body)


def make_document(
    openzaak: ApiClient,
    registry: ResourceRegistry,
    informatieobjecttype: str,
    inhoud: str = "podiumd-tests",
    **fields: object,
) -> JsonObject:
    """An enkelvoudig informatieobject with text inhoud whose titel carries the run tag."""
    body: dict[str, object] = {
        "bronorganisatie": TEST_CATALOGUS_RSIN,
        "creatiedatum": today(),
        "titel": registry.tagged("document"),
        "auteur": "podiumd-tests",
        "taal": "dut",
        "bestandsnaam": "ptest.txt",
        "formaat": "text/plain",
        "informatieobjecttype": informatieobjecttype,
        "inhoud": base64.b64encode(inhoud.encode()).decode(),
        "bestandsomvang": len(inhoud.encode()),
        "indicatieGebruiksrecht": False,
        "vertrouwelijkheidaanduiding": "openbaar",
        **fields,
    }
    return _create(openzaak, registry, f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", body)


def link_document(
    openzaak: ApiClient, registry: ResourceRegistry, zaak: JsonObject, document: JsonObject
) -> JsonObject:
    """A zaakinformatieobject linking a document to a zaak."""
    body = {"zaak": zaak["url"], "informatieobject": document["url"], "titel": registry.tagged("koppeling")}
    return _create(openzaak, registry, f"{ZAKEN}/zaakinformatieobjecten", body)


def clean_up_new_documents(openzaak: ApiClient, registry: ResourceRegistry, zaak: JsonObject) -> None:
    """Delete, at cleanup, the documents another component links to the zaak (e.g. a portal upload).

    Register it after the zaak, so it runs before the zaak is deleted.
    """

    def delete() -> None:
        for link in openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])}):
            openzaak.delete(str(link["url"]))
            openzaak.delete(str(link["informatieobject"]))

    registry.add(f"new documents of zaak {zaak['url']}", delete)


def make_besluit(openzaak: ApiClient, registry: ResourceRegistry, besluittype: str, **fields: object) -> JsonObject:
    """A besluit of a besluittype whose toelichting carries the run tag."""
    body: dict[str, object] = {
        "verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN,
        "besluittype": besluittype,
        "datum": today(),
        "ingangsdatum": today(),
        "toelichting": registry.tagged("besluit"),
        **fields,
    }
    return _create(openzaak, registry, f"{BESLUITEN}/besluiten", body)


def make_concept_zaaktype(
    openzaak: ApiClient, registry: ResourceRegistry, catalogus: str, **fields: object
) -> JsonObject:
    """A concept zaaktype in a catalogus; concepts can be deleted, published zaaktypen cannot."""
    body: dict[str, object] = {
        "identificatie": registry.tagged(f"zaaktype-{secrets.token_hex(3)}"),
        "omschrijving": "podiumd-tests concept",
        "vertrouwelijkheidaanduiding": "openbaar",
        "doel": "podiumd-tests",
        "aanleiding": "podiumd-tests",
        "indicatieInternOfExtern": "extern",
        "handelingInitiator": "Indienen",
        "onderwerp": "Test",
        "handelingBehandelaar": "Behandelen",
        "doorlooptijd": "P30D",
        "opschortingEnAanhoudingMogelijk": False,
        "verlengingMogelijk": False,
        "publicatieIndicatie": False,
        "productenOfDiensten": [],
        "referentieproces": {"naam": "podiumd-tests"},
        "verantwoordelijke": TEST_CATALOGUS_RSIN,
        "beginGeldigheid": today(),
        "versiedatum": today(),
        "catalogus": catalogus,
        "besluittypen": [],
        "deelzaaktypen": [],
        "gerelateerdeZaaktypen": [],
        **fields,
    }
    return _create(openzaak, registry, f"{CATALOGI}/zaaktypen", body)
