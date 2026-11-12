"""Open Zaak test data through the ZGW APIs; every factory registers its deleter."""

from __future__ import annotations

import base64
import secrets

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import strings
from podiumd_tests.responses import expect_status
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


def delete_zaak(openzaak: ApiClient, url: str, *, with_documents: bool = False) -> None:
    """DELETE a zaak, retrying until it is gone; with_documents also its documents, which Open Zaak keeps.

    Open Zaak 1.29.3 answers 500 on deleting a zaak with a resultaat although it deletes it
    (the ETag of the deleted resultaat is recalculated; test_closed_zaak_delete_answers_204
    tracks it). It also answers 500 and keeps the zaak when another client (ZAC) adds a rol
    during the delete. A 500 counts as deleted only when the zaak is gone.
    """

    def is_deleted() -> bool:
        response = openzaak.request(
            "DELETE", url, HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND, HTTPStatus.INTERNAL_SERVER_ERROR
        )
        if response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
            openzaak.request("GET", url, HTTPStatus.NOT_FOUND)
        return True

    documents = (
        [str(link["informatieobject"]) for link in openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": url})]
        if with_documents
        else []
    )
    wait_until(is_deleted, timeout=DELETE_TIMEOUT, description=f"DELETE {url}")
    for document in documents:
        openzaak.delete(document)


def make_zaak(openzaak: ApiClient, registry: ResourceRegistry, zaaktype: str, **fields: object) -> JsonObject:
    """Create a zaak of a zaaktype whose omschrijving carries the run tag; fields override defaults, None drops one."""
    body: dict[str, object] = {
        "bronorganisatie": TEST_CATALOGUS_RSIN,
        "verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN,
        "zaaktype": zaaktype,
        "startdatum": today(),
        "omschrijving": registry.tagged("zaak"),
        "vertrouwelijkheidaanduiding": "openbaar",
        **fields,
    }
    given = {field: value for field, value in body.items() if value is not None}
    zaak = openzaak.post(f"{ZAKEN}/zaken", given)
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


def published_zaaktype(openzaak: ApiClient, identificatie: str, step: str) -> JsonObject:
    """Return the published zaaktype with this identificatie that bootstrap step `step` creates."""
    zaaktypen = openzaak.list(f"{CATALOGI}/zaaktypen", {"identificatie": identificatie})
    found = [zaaktype for zaaktype in zaaktypen if not zaaktype.get("concept")]
    if not found:
        msg = f"zaaktype {identificatie} missing: bootstrap step {step}"
        raise LookupError(msg)
    return found[0]


def zaaktype_parts(openzaak: ApiClient, zaaktype: JsonObject) -> ZaaktypeParts:
    """Look up the statustypen, roltypen, informatieobjecttype, eigenschappen, besluittype and resultaattypen."""
    url = str(zaaktype["url"])
    statustypen = sorted(
        openzaak.list(f"{CATALOGI}/statustypen", {"zaaktype": url}),
        key=lambda statustype: int(str(statustype["volgnummer"])),
    )
    roltypen = {
        str(roltype["omschrijvingGeneriek"]): str(roltype["url"])
        for roltype in openzaak.list(f"{CATALOGI}/roltypen", {"zaaktype": url})
    }
    eigenschappen = {
        str(eigenschap["naam"]): str(eigenschap["url"])
        for eigenschap in openzaak.list(f"{CATALOGI}/eigenschappen", {"zaaktype": url})
    }
    besluittypen = openzaak.list(f"{CATALOGI}/besluittypen", {"zaaktypen": url})
    resultaattypen = [
        str(resultaattype["url"]) for resultaattype in openzaak.list(f"{CATALOGI}/resultaattypen", {"zaaktype": url})
    ]
    iots = strings(zaaktype.get("informatieobjecttypen"))
    return ZaaktypeParts(
        url, statustypen, roltypen, iots[0], eigenschappen, str(besluittypen[0]["url"]), resultaattypen
    )


def status_body(zaak: JsonObject, statustype: str, toelichting: str = "", gezet: datetime | None = None) -> JsonObject:
    """Return the body of a status of a zaak, set now or at gezet."""
    return {
        "zaak": zaak["url"],
        "statustype": statustype,
        "datumStatusGezet": (gezet or datetime.now(tz=UTC)).isoformat(),
        "statustoelichting": toelichting,
    }


def make_status(
    openzaak: ApiClient, zaak: JsonObject, statustype: str, toelichting: str = "", gezet: datetime | None = None
) -> JsonObject:
    """Create a status of a zaak, set now or at gezet; deleted with the zaak."""
    return openzaak.post(f"{ZAKEN}/statussen", status_body(zaak, statustype, toelichting, gezet))


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
    """Create a rol on a zaak; identificatie is the betrokkeneIdentificatie (e.g. inpBsn=...)."""
    body: dict[str, object] = {
        "zaak": zaak["url"],
        "betrokkeneType": betrokkene_type,
        "roltype": roltype,
        "roltoelichting": registry.tagged("rol"),
        "betrokkeneIdentificatie": identificatie,
    }
    return _create(openzaak, registry, f"{ZAKEN}/rollen", body)


def document_body(
    registry: ResourceRegistry, informatieobjecttype: str, size: int, **fields: object
) -> dict[str, object]:
    """Build an enkelvoudig informatieobject of size bytes whose titel carries the run tag; fields override defaults."""
    return {
        "bronorganisatie": TEST_CATALOGUS_RSIN,
        "creatiedatum": today(),
        "titel": registry.tagged("document"),
        "auteur": "podiumd-tests",
        "taal": "dut",
        "bestandsnaam": "ptest.txt",
        "formaat": "text/plain",
        "informatieobjecttype": informatieobjecttype,
        "bestandsomvang": size,
        "indicatieGebruiksrecht": False,
        "vertrouwelijkheidaanduiding": "openbaar",
        **fields,
    }


def make_document(
    openzaak: ApiClient,
    registry: ResourceRegistry,
    informatieobjecttype: str,
    inhoud: str = "podiumd-tests",
    **fields: object,
) -> JsonObject:
    """Create an enkelvoudig informatieobject with text inhoud whose titel carries the run tag."""
    content = inhoud.encode()
    body = document_body(registry, informatieobjecttype, len(content), **fields)
    body = {"inhoud": base64.b64encode(content).decode(), **body}
    return _create(openzaak, registry, f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", body)


def make_document_in_parts(
    openzaak: ApiClient, registry: ResourceRegistry, informatieobjecttype: str, content: bytes, **fields: object
) -> JsonObject:
    """Create a document without inhoud whose bestandsdelen carry content; it stays locked (unlock merges them)."""
    body = document_body(registry, informatieobjecttype, len(content), formaat="application/octet-stream", **fields)
    document = _create(openzaak, registry, f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", body)
    # The parts are multipart uploads: the client's JSON Content-Type must not go along.
    headers = {name: value for name, value in openzaak.headers().items() if name.lower() != "content-type"}
    offset = 0
    for part in entries(document.get("bestandsdelen")):
        size = int(str(part["omvang"]))
        upload = openzaak.http.put(
            str(part["url"]),
            headers=headers,
            data={"lock": document["lock"]},
            files={"inhoud": ("deel", content[offset : offset + size])},
        )
        expect_status(upload, HTTPStatus.OK)
        offset += size
    return document


def make_gebruiksrechten(openzaak: ApiClient, registry: ResourceRegistry, document: JsonObject) -> JsonObject:
    """Create gebruiksrechten of a document; Open Zaak then sets its indicatieGebruiksrecht to true."""
    body = {
        "informatieobject": document["url"],
        "startdatum": f"{today()}T00:00:00Z",
        "omschrijvingVoorwaarden": registry.tagged("gebruiksrechten"),
    }
    return _create(openzaak, registry, f"{DOCUMENTEN}/gebruiksrechten", body)


def link_document(
    openzaak: ApiClient, registry: ResourceRegistry, zaak: JsonObject, document: JsonObject
) -> JsonObject:
    """Create a zaakinformatieobject linking a document to a zaak."""
    body = {"zaak": zaak["url"], "informatieobject": document["url"], "titel": registry.tagged("koppeling")}
    return _create(openzaak, registry, f"{ZAKEN}/zaakinformatieobjecten", body)


def clean_up_new_documents(openzaak: ApiClient, registry: ResourceRegistry, zaak: JsonObject) -> None:
    """Delete, at cleanup, the documents another component links to the zaak (e.g. a portal upload).

    Register it after the zaak, so it runs before the zaak is deleted.
    """

    registry.add(f"new documents of zaak {zaak['url']}", lambda: delete_documents_of(openzaak, str(zaak["url"])))


def delete_documents_of(openzaak: ApiClient, zaak: str) -> None:
    """Delete the documents linked to a zaak, with their links."""
    for link in openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": zaak}):
        openzaak.delete(str(link["url"]))
        openzaak.delete(str(link["informatieobject"]))


def make_besluit(openzaak: ApiClient, registry: ResourceRegistry, besluittype: str, **fields: object) -> JsonObject:
    """Create a besluit whose identificatie and toelichting carry the run tag; fields override defaults, None drops one.

    The identificatie is the suite's own: Open Zaak 1.29.3 generates the same one for concurrent creates (open-zaak-8).
    """
    body: dict[str, object] = {
        "identificatie": registry.tagged(f"besluit-{secrets.token_hex(4)}"),
        "verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN,
        "besluittype": besluittype,
        "datum": today(),
        "ingangsdatum": today(),
        "toelichting": registry.tagged("besluit"),
        **fields,
    }
    given = {key: value for key, value in body.items() if value is not None}
    besluit = openzaak.post(f"{BESLUITEN}/besluiten", given)
    url = str(besluit["url"])
    registry.add(f"besluit {url}", lambda: delete_besluit(openzaak, url))
    return besluit


def delete_besluit(openzaak: ApiClient, url: str) -> None:
    """DELETE a besluit after its besluitinformatieobjecten: Open Zaak 1.29.3 answers 500 otherwise (open-zaak-7)."""
    for link in openzaak.list(f"{BESLUITEN}/besluitinformatieobjecten", {"besluit": url}):
        openzaak.delete(str(link["url"]))
    openzaak.delete(url)


def zaaktype_body(registry: ResourceRegistry, catalogus: str, **fields: object) -> dict[str, object]:
    """Build a zaaktype of a catalogus whose identificatie carries the run tag; fields override defaults."""
    return {
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


def make_concept_zaaktype(
    openzaak: ApiClient, registry: ResourceRegistry, catalogus: str, **fields: object
) -> JsonObject:
    """Create a concept zaaktype in a catalogus; concepts can be deleted, published zaaktypen cannot."""
    return _create(openzaak, registry, f"{CATALOGI}/zaaktypen", zaaktype_body(registry, catalogus, **fields))
