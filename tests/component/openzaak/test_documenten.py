"""Open Zaak documenten: upload, link to a zaak, lock and new versions, signature, integrity.

Ported from TA interaction 03 and regression 49, 51 and 64 (64 covers 49 and 51b).
"""

from __future__ import annotations

import base64
import hashlib

from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import invalid_codes
from podiumd_tests.responses import invalid_names
from podiumd_tests.seed.catalogi import make_concept_iot
from podiumd_tests.seed.openzaak import DOCUMENTEN
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_document_in_parts
from podiumd_tests.seed.openzaak import make_gebruiksrechten
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import text_document_body
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


def new_version(openzaak: ApiClient, document: JsonObject, inhoud: str, **fields: object) -> JsonObject:
    """Lock, PUT a new version with inhoud and fields, unlock; the new version."""
    url = str(document["url"])
    lock = openzaak.request("POST", f"{url}/lock", 200, json={}).json()["lock"]
    body = {
        **document,
        **fields,
        "inhoud": base64.b64encode(inhoud.encode()).decode(),
        "bestandsomvang": len(inhoud.encode()),
        "lock": lock,
    }
    for key in ("url", "versie", "beginRegistratie", "locked", "bestandsdelen"):
        body.pop(key, None)
    updated = openzaak.request("PUT", url, 200, json=body).json()
    openzaak.request("POST", f"{url}/unlock", 204, json={"lock": lock})
    return updated


@pytest.mark.source(
    "TA interaction/03-document-koppeling.spec.ts",
    "A document is linked to a zaak in two steps, EnkelvoudigInformatieObject and ZaakInformatieObject, as ZGW prescribes.",
)
@pytest.mark.core
@pytest.mark.scenario("""
    Given a zaak and an informatieobject in Open Zaak
    When the informatieobject is linked to the zaak
    Then the zaak's zaakinformatieobjecten hold only that informatieobject
""")
def test_document_linked_to_zaak(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A document linked to a zaak shows in the zaak's zaakinformatieobjecten (TA int-03)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    link_document(openzaak, registry, zaak, document)
    linked = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    assert [z["informatieobject"] for z in entries(linked)] == [document["url"]]


@pytest.mark.source(
    "TA regression/64-document-lifecycle.spec.ts",
    "Document lifecycle: upload, sign, make definitief, add version 2 and unlock.",
)
@pytest.mark.source(
    "TA regression/49-document-download.spec.ts", "A document upload stores the content and its download metadata."
)
@pytest.mark.source(
    "TA regression/51-document-crud-edges.spec.ts",
    "Document edge cases: gebruiksrecht, concept to definitief, ondertekening and integriteit.",
)
@pytest.mark.scenario("""
    When an informatieobject without gebruiksrecht is uploaded to Open Zaak
    Then it is version 1 with the content's size and a download link for that version
    When it is locked, made definitief, signed and unlocked
    Then it is version 2 with status definitief
    When it gets new content the same way
    Then it is version 3 with the new content's size
""")
def test_document_versions_and_definitief(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """Version 1 stores the bestandsomvang; lock/PUT/unlock makes it definitief and signed, then version 3 (TA reg-49, 51b, 64)."""
    document = make_document(
        openzaak, registry, parts.informatieobjecttype, inhoud="versie één", indicatieGebruiksrecht=None
    )
    assert (document["versie"], document["bestandsomvang"], document["indicatieGebruiksrecht"]) == (
        1,
        len("versie één".encode()),
        None,
    )
    assert str(document["inhoud"]).endswith("/download?versie=1")
    signed = new_version(
        openzaak, document, "versie één", status="definitief", ondertekening={"soort": "digitaal", "datum": today()}
    )
    assert (signed["versie"], signed["status"]) == (2, "definitief")
    newer = new_version(openzaak, signed, "versie drie")
    assert (newer["versie"], newer["bestandsomvang"]) == (3, len(b"versie drie"))
    eerste = openzaak.get(str(document["url"]), {"versie": "1"})
    assert (eerste["versie"], eerste["status"], eerste["bestandsomvang"]) == (
        1,
        document["status"],
        len("versie één".encode()),
    )


@pytest.mark.source(
    "TA regression/51-document-crud-edges.spec.ts",
    "Document edge cases: gebruiksrecht, concept to definitief, ondertekening and integriteit.",
)
@pytest.mark.scenario("""
    When an informatieobject is uploaded to Open Zaak with a SHA-256 integriteit and a digital ondertekening
    Then Open Zaak stores the integriteit and the ondertekening as sent
""")
def test_document_integriteit_and_ondertekening(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """integriteit (sha_256) and ondertekening are stored as sent (TA reg-51c, 51d)."""
    integriteit = {"algoritme": "sha_256", "waarde": hashlib.sha256(b"podiumd-tests").hexdigest(), "datum": today()}
    ondertekening = {"soort": "digitaal", "datum": today()}
    document = make_document(
        openzaak, registry, parts.informatieobjecttype, integriteit=integriteit, ondertekening=ondertekening
    )
    assert (document["integriteit"], document["ondertekening"]) == (integriteit, ondertekening)


AUDITTRAIL_BUG = (
    "[open-zaak-3] Open Zaak 1.29.3: audittrail endpoints check the component 'audittrails' (AuditTrail's app label), "
    "so only clients with heeft_alle_autorisaties can read them; not yet reported upstream"
)


@pytest.mark.source(
    "TA regression/64-document-lifecycle.spec.ts",
    "Document lifecycle: upload, sign, make definitief, add version 2 and unlock.",
)
@pytest.mark.xfail(strict=True, reason=AUDITTRAIL_BUG)
@pytest.mark.scenario("""
    Given an informatieobject in Open Zaak
    When an API client with audittrail rights on the catalogus reads its audittrail
    Then Open Zaak returns the audittrail
""")
def test_document_audittrail_with_catalogus_rights(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """A client with audittrails.lezen on the catalogus reads a document's audittrail (TA reg-64)."""
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    assert openzaak.request("GET", f"{document['url']}/audittrail", 200).json()


# Concurrent same-name unlocks; four hit the race in every try on minikube.
SAME_NAME_UPLOADS = 4
# Over Open Zaak's in-memory upload limit, so the parts are merged through a file.
LARGE_DOCUMENT = 3_000_000


@pytest.mark.xfail(
    reason="[open-zaak-4] Open Zaak 1.29.3 merges the bestandsdelen of documents with the same bestandsnaam in one"
    " temporary file: concurrent unlocks answer 500 or store another document's content; fixed in 1.31.0"
    " (open-zaak#2592). A race: it may not hit",
)
@pytest.mark.source(
    "upstream open-zaak/open-zaak CHANGELOG.rst",
    "1.31.0, #2592: documents with the same file name saved at the same time overwrote each other's content.",
)
@pytest.mark.scenario("""
    Given four large informatieobjecten uploaded in parts under one bestandsnaam
    When all four are unlocked at the same time
    Then every unlock succeeds
    And each informatieobject downloads its own content
""")
def test_large_documents_with_the_same_name_keep_their_own_content(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """Documents uploaded in parts under one bestandsnaam and unlocked at once each keep their own content."""
    contents = [bytes([ord("A") + i]) * LARGE_DOCUMENT for i in range(SAME_NAME_UPLOADS)]
    name = f"{registry.tagged('deel')}.bin"
    documents = [
        make_document_in_parts(openzaak, registry, parts.informatieobjecttype, c, bestandsnaam=name) for c in contents
    ]

    def unlock(document: JsonObject) -> int:
        body = {"lock": document["lock"]}
        return openzaak.request("POST", f"{document['url']}/unlock", 204, 500, json=body).status_code

    with ThreadPoolExecutor(SAME_NAME_UPLOADS) as pool:
        unlocked = list(pool.map(unlock, documents))
    stored = []
    for document in documents:
        download = openzaak.http.get(f"{document['url']}/download", headers={**openzaak.headers(), "Accept": "*/*"})
        stored.append(download.content if download.status_code == HTTPStatus.OK else b"")
    assert unlocked == [HTTPStatus.NO_CONTENT for _ in range(SAME_NAME_UPLOADS)]
    assert [s == c for s, c in zip(stored, contents, strict=True)] == [True for _ in range(SAME_NAME_UPLOADS)]


NOWHERE = "http://openzaak.invalid/documenten/api/v1/enkelvoudiginformatieobjecten/00000000-0000-0000-0000-000000000000"


def objectinformatieobjecten(openzaak: ApiClient, document: JsonObject) -> list[JsonObject]:
    """The objectinformatieobjecten Documenten API keeps for a document."""
    return entries(openzaak.list(f"{DOCUMENTEN}/objectinformatieobjecten", {"informatieobject": str(document["url"])}))


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rules zrc-004, zrc-005, drc-00x",
    "A zaakinformatieobject gets aardRelatie hoort_bij and a registratiedatum; Documenten API mirrors it as an "
    "objectinformatieobject, created and deleted with it; its zaak and informatieobject cannot change.",
)
@pytest.mark.scenario("""
    Given a zaak and a document in Open Zaak
    When the document is linked to the zaak
    Then the link is registered now, as "hoort bij"
    And the document's record in Documenten names the zaak
    And the link cannot be moved to another zaak or document
    And deleting the link removes the record in Documenten
""")
def test_zaak_document_link_is_mirrored_and_fixed(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """A zaakinformatieobject has fixed zaak and informatieobject and lives as long as its objectinformatieobject."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    other_zaak = make_zaak(openzaak, registry, parts.zaaktype)
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    other_document = make_document(openzaak, registry, parts.informatieobjecttype)
    link = link_document(openzaak, registry, zaak, document)
    assert str(link["aardRelatieWeergave"]).lower().startswith("hoort bij"), link["aardRelatieWeergave"]
    assert str(link["registratiedatum"]).startswith(today()), link["registratiedatum"]
    mirrored = objectinformatieobjecten(openzaak, document)
    assert [(o["object"], o["objectType"]) for o in mirrored] == [(zaak["url"], "zaak")]
    for field, value in (("zaak", other_zaak["url"]), ("informatieobject", other_document["url"])):
        response = openzaak.request("PATCH", str(link["url"]), HTTPStatus.BAD_REQUEST, json={field: value})
        assert field in invalid_names(response)
    openzaak.delete(str(link["url"]))
    assert objectinformatieobjecten(openzaak, document) == []


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule zrc-003",
    "A zaakinformatieobject whose informatieobject URL does not resolve is refused.",
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When it is linked to a document that does not exist
    Then Open Zaak refuses the link and names the informatieobject
""")
def test_link_to_a_document_that_does_not_exist_is_refused(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """POST of a zaakinformatieobject with an informatieobject URL that does not resolve answers 400, not 500."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    body = {"zaak": zaak["url"], "informatieobject": NOWHERE}
    response = openzaak.request("POST", f"{ZAKEN}/zaakinformatieobjecten", HTTPStatus.BAD_REQUEST, json=body)
    assert "informatieobject" in invalid_names(response)


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rules drc-002 to drc-004",
    "An objectinformatieobject is refused for an object that does not resolve or is no zaak, a second time, and "
    "without the zaakinformatieobject in Zaken API.",
)
@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "object-does-not-exist",
            marks=pytest.mark.xfail(
                strict=True,
                reason="[open-zaak-6] Open Zaak 1.29.3 answers 500 (no Service for the object URL's host); "
                "not yet reported upstream",
            ),
        ),
        "object-is-no-zaak",
        "already-mirrored",
        "not-linked",
    ],
)
@pytest.mark.scenario("""
    Given a zaak and a document in Open Zaak
    When a record linking them is added to Documenten directly
    Then Open Zaak refuses it unless the zaak exists and holds the document in Zaken
    And it refuses a second record for the same link
""")
def test_objectinformatieobject_follows_the_zaak(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, case: str
) -> None:
    """POST of an objectinformatieobject that does not mirror a zaakinformatieobject answers 400."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    target = {
        "object-does-not-exist": NOWHERE.replace("documenten/api/v1/enkelvoudiginformatieobjecten", f"{ZAKEN}/zaken"),
        "object-is-no-zaak": str(parts.statustypen[0]["url"]),
    }.get(case, str(zaak["url"]))
    if case == "already-mirrored":
        link_document(openzaak, registry, zaak, document)
    body = {"informatieobject": document["url"], "object": target, "objectType": "zaak"}
    response = openzaak.request("POST", f"{DOCUMENTEN}/objectinformatieobjecten", HTTPStatus.BAD_REQUEST, json=body)
    expected = "unique" if case == "already-mirrored" else "inconsistent-relation"
    assert invalid_codes(response) == [expected], response.text


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule drc-006",
    "indicatieGebruiksrecht is null until gebruiksrechten exist; it is true with them and null again without.",
)
@pytest.mark.scenario("""
    Given a new document in Open Zaak
    Then its gebruiksrechten are not recorded
    And it cannot be marked as having gebruiksrechten without them
    When gebruiksrechten are recorded, it has gebruiksrechten
    And when they are deleted, they are no longer recorded
""")
def test_indicatie_gebruiksrecht_follows_the_gebruiksrechten(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """indicatieGebruiksrecht: null at create, true not settable by hand, true with gebruiksrechten, null after."""
    document = make_document(openzaak, registry, parts.informatieobjecttype, indicatieGebruiksrecht=None)
    url = str(document["url"])
    assert document["indicatieGebruiksrecht"] is None
    lock = openzaak.request("POST", f"{url}/lock", HTTPStatus.OK, json={}).json()["lock"]
    body = {"indicatieGebruiksrecht": True, "lock": lock}
    response = openzaak.request("PATCH", url, HTTPStatus.BAD_REQUEST, json=body)
    assert "indicatieGebruiksrecht" in invalid_names(response)
    openzaak.request("POST", f"{url}/unlock", HTTPStatus.NO_CONTENT, json={"lock": lock})
    gebruiksrechten = make_gebruiksrechten(openzaak, registry, document)
    assert openzaak.get(url)["indicatieGebruiksrecht"] is True
    openzaak.delete(str(gebruiksrechten["url"]))
    assert openzaak.get(url)["indicatieGebruiksrecht"] is None


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule drc-009",
    "A document changes only with its lockId; only a client with documenten.geforceerd-unlock unlocks without it.",
)
@pytest.mark.scenario("""
    Given a locked document in Open Zaak
    When it is changed without the lock or with a wrong one
    Then Open Zaak refuses the change
    And a client without the right to force an unlock cannot unlock it without the lock
    And a client with that right can
""")
def test_locked_document_needs_its_lock(
    openzaak: ApiClient, openzaak_gesloten: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """PATCH without or with a wrong lock is a 400; unlock without the lock needs documenten.geforceerd-unlock."""
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    url = str(document["url"])
    openzaak.request("POST", f"{url}/lock", HTTPStatus.OK, json={})
    for lock in ({}, {"lock": "0" * 32}):
        body = {"titel": registry.tagged("titel"), **lock}
        response = openzaak.request("PATCH", url, HTTPStatus.BAD_REQUEST, json=body)
        assert invalid_names(response), response.text
    openzaak_gesloten.request("POST", f"{url}/unlock", HTTPStatus.BAD_REQUEST, *REFUSED, json={})
    openzaak.request("POST", f"{url}/unlock", HTTPStatus.NO_CONTENT, json={})
    assert openzaak.get(url)["locked"] is False


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule drc-005",
    "A document still in progress cannot have an ontvangstdatum.",
)
@pytest.mark.parametrize("status", ["in_bewerking", "ter_vaststelling"])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.scenario("""
    Given a document that is in progress or awaiting approval
    When it is given an ontvangstdatum, on create or on change
    Then Open Zaak refuses it: such a status does not apply to a received document
""")
def test_document_in_progress_has_no_ontvangstdatum(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, status: str, method: str
) -> None:
    """status in_bewerking or ter_vaststelling with an ontvangstdatum answers 400 on POST and PATCH."""
    fields = {"status": status, "ontvangstdatum": today()}
    path = f"{DOCUMENTEN}/enkelvoudiginformatieobjecten"
    if method == "POST":
        body = text_document_body(registry, parts.informatieobjecttype, **fields)
        response = openzaak.request("POST", path, HTTPStatus.BAD_REQUEST, json=body)
    else:
        document = make_document(openzaak, registry, parts.informatieobjecttype)
        url = str(document["url"])
        lock = openzaak.request("POST", f"{url}/lock", HTTPStatus.OK, json={}).json()["lock"]
        response = openzaak.request("PATCH", url, HTTPStatus.BAD_REQUEST, json={**fields, "lock": lock})
        openzaak.request("POST", f"{url}/unlock", HTTPStatus.NO_CONTENT, json={"lock": lock})
    assert invalid_codes(response) == ["invalid_for_received"], response.text


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule drc-007",
    "A document without vertrouwelijkheidaanduiding gets its informatieobjecttype's; an explicit one is kept.",
)
@pytest.mark.scenario("""
    Given the test informatieobjecttype
    When a document is created without a vertrouwelijkheidaanduiding
    Then it has the vertrouwelijkheidaanduiding of its informatieobjecttype
    And a document created with one keeps it
""")
def test_document_vertrouwelijkheidaanduiding_defaults_to_the_informatieobjecttypes(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """A document without vertrouwelijkheidaanduiding takes the informatieobjecttype's; an explicit value is kept."""
    iot = openzaak.get(parts.informatieobjecttype)
    body = text_document_body(registry, parts.informatieobjecttype)
    body.pop("vertrouwelijkheidaanduiding")
    derived = openzaak.post(f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", body)
    registry.add(f"document {derived['url']}", lambda: openzaak.delete(str(derived["url"])))
    explicit = make_document(openzaak, registry, parts.informatieobjecttype, vertrouwelijkheidaanduiding="geheim")
    assert derived["vertrouwelijkheidaanduiding"] == iot["vertrouwelijkheidaanduiding"]
    assert explicit["vertrouwelijkheidaanduiding"] == "geheim"


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW features, DRC Identificatie uniek",
    "A document's identificatie is unique per bronorganisatie, on create and on change.",
)
@pytest.mark.parametrize(
    "method",
    [
        "POST",
        pytest.param(
            "PATCH",
            marks=pytest.mark.xfail(
                strict=True,
                reason="[open-zaak-9] Open Zaak 1.29.3 accepts a PATCH to another document's identificatie (the update "
                "serializer drops UniekeIdentificatieValidator); not yet reported upstream",
            ),
        ),
    ],
)
@pytest.mark.scenario("""
    Given a document in Open Zaak
    When a second document is created or changed to have the same identificatie
    Then Open Zaak refuses it and names the identificatie
""")
def test_document_identificatie_is_unique(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, method: str
) -> None:
    """POST or PATCH to an identificatie in use for the same bronorganisatie answers 400."""
    eerste = make_document(openzaak, registry, parts.informatieobjecttype)
    if method == "POST":
        body = text_document_body(registry, parts.informatieobjecttype, identificatie=eerste["identificatie"])
        response = openzaak.request(
            "POST", f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", HTTPStatus.BAD_REQUEST, json=body
        )
    else:
        tweede = make_document(openzaak, registry, parts.informatieobjecttype)
        url = str(tweede["url"])
        lock = openzaak.request("POST", f"{url}/lock", HTTPStatus.OK, json={}).json()["lock"]
        unlock = {"lock": lock}
        registry.add(
            f"unlock {url}", lambda: openzaak.request("POST", f"{url}/unlock", HTTPStatus.NO_CONTENT, json=unlock)
        )
        change = {"identificatie": eerste["identificatie"], "lock": lock}
        response = openzaak.request("PATCH", url, HTTPStatus.BAD_REQUEST, json=change)
    assert "identificatie" in invalid_names(response), response.text


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule drc-007",
    "A document's vertrouwelijkheidaanduiding is one of the choices or derived from its informatieobjecttype.",
)
@pytest.mark.xfail(
    strict=True,
    reason="[open-zaak-10] Open Zaak 1.29.3 answers 500 to a document with an empty vertrouwelijkheidaanduiding "
    "(has_auth filters on None) for a client without heeft_alle_autorisaties; not yet reported upstream",
)
@pytest.mark.scenario("""
    When a document is created with an empty vertrouwelijkheidaanduiding
    Then Open Zaak refuses it as invalid, or gives it the vertrouwelijkheidaanduiding of its informatieobjecttype
""")
def test_document_with_empty_vertrouwelijkheidaanduiding_is_no_server_error(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """POST of a document with vertrouwelijkheidaanduiding "" answers 400 or 201, not 500."""
    body = text_document_body(registry, parts.informatieobjecttype, vertrouwelijkheidaanduiding="")
    path = f"{DOCUMENTEN}/enkelvoudiginformatieobjecten"
    response = openzaak.request("POST", path, HTTPStatus.BAD_REQUEST, HTTPStatus.CREATED, json=body)
    if response.status_code == HTTPStatus.CREATED:
        url = str(response.json()["url"])
        registry.add(f"document {url}", lambda: openzaak.delete(url))


@pytest.mark.source(
    "external OneGround/ZGW-APIs-postman-tests ZGW business rule drc-001",
    "A document cannot have an informatieobjecttype that is still a concept.",
)
@pytest.mark.requires("cluster")
@pytest.mark.scenario("""
    Given a concept informatieobjecttype in the test catalogus
    When a document of that informatieobjecttype is created
    Then Open Zaak refuses it: the informatieobjecttype is not published
""")
def test_document_needs_a_published_informatieobjecttype(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, test_zaaktype: JsonObject
) -> None:
    """POST of a document with a concept informatieobjecttype answers 400 not-published."""
    iot = make_concept_iot(podiumd_env, openzaak, registry, str(test_zaaktype["catalogus"]))
    body = text_document_body(registry, str(iot["url"]))
    path = f"{DOCUMENTEN}/enkelvoudiginformatieobjecten"
    response = openzaak.request("POST", path, HTTPStatus.BAD_REQUEST, json=body)
    assert invalid_codes(response) == ["not-published"], response.text
