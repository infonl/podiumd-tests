"""ZAC: documents of a zaak (verplaatsen, ontkoppelen, vergrendelen, versies, ondertekenen, uploads), as its UI does them.

The zaak is of the zaaktype ZAC handles productaanvragen for; the test admin is ZAC beheerder of every domain.
"""

from __future__ import annotations

import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import strings
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import DOCUMENTEN
from podiumd_tests.zac import zaak_historie
from podiumd_tests.zac_documents import FILES
from podiumd_tests.zac_documents import ONTKOPPELDE_DOCUMENTEN
from podiumd_tests.zac_documents import delete_ontkoppeld_document
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import max_file_size_mb
from podiumd_tests.zac_documents import nieuwe_versie
from podiumd_tests.zac_documents import ontkoppel_document
from podiumd_tests.zac_documents import ontkoppelde_documenten
from podiumd_tests.zac_documents import taal
from podiumd_tests.zac_documents import upload
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_documents import verplaats_document
from podiumd_tests.zac_documents import zaak_documents

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, documenten-mail).",
    ),
]

REDEN = "podiumd-tests ontkoppelen"


def _uuids(zac: requests.Session, zac_url: str, zaak: JsonObject) -> list[object]:
    """The uuids of the zaak's documents in ZAC."""
    return [document.get("uuid") for document in zaak_documents(zac, zac_url, zaak)]


def _ontkoppeld(zac: requests.Session, zac_url: str, zaak: JsonObject, document: JsonObject) -> JsonObject | None:
    """The document's entry in ZAC's ontkoppelde documenten of the zaak, or None."""
    found = ontkoppelde_documenten(zac, zac_url, zaak)
    return next((item for item in found if item.get("documentUUID") == document["uuid"]), None)


def _toelichtingen(zac: requests.Session, zac_url: str, zaak: JsonObject, actie: str) -> list[str]:
    """The toelichtingen of the zaak's historie lines of this actie."""
    return strings(
        [line.get("toelichting") for line in zaak_historie(zac, zac_url, zaak) if line.get("actie") == actie]
    )


@pytest.mark.scenario("""
    Given two zaken in ZAC, the first with a document
    When the behandelaar moves the document to the second zaak
    Then the second zaak has the document and the first no longer
    And the second zaak's historie records the move
""")
def test_document_is_moved_to_another_zaak(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """Verplaatsen from a zaak links the document to the other zaak only; GEKOPPELD in that zaak's historie."""
    zaak, ander = zac_zaak(), zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry)
    moved = verplaats_document(zac, urls["zac"], document, str(zaak["identificatie"]), ander)
    expect_status(moved, HTTPStatus.NO_CONTENT, HTTPStatus.OK)
    assert document["uuid"] not in _uuids(zac, urls["zac"], zaak)
    assert document["uuid"] in _uuids(zac, urls["zac"], ander)
    # Open Zaak's toelichting of the moved link, without ZAC's "Verplaatst: " of a move from a list.
    assert f"{zaak['identificatie']} -> {ander['identificatie']}" in _toelichtingen(
        zac, urls["zac"], ander, "GEKOPPELD"
    )


@pytest.mark.scenario("""
    Given a zaak in ZAC with a document
    When the behandelaar ontkoppelt the document with a reden
    Then the zaak no longer has it and its historie shows the reden
    And the ontkoppelde documenten list it with the zaak and the reden
    When the behandelaar koppelt it from the ontkoppelde documenten to another zaak
    Then the other zaak has the document and the ontkoppelde documenten no longer list it
""")
def test_ontkoppeld_document_is_gekoppeld_to_another_zaak(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """Ontkoppelen lists the document in ontkoppelde documenten; verplaatsen from there links it to another zaak."""
    zaak, ander = zac_zaak(), zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry)
    expect_status(ontkoppel_document(zac, urls["zac"], zaak, document, REDEN, registry), HTTPStatus.NO_CONTENT)
    assert document["uuid"] not in _uuids(zac, urls["zac"], zaak)
    assert f"Ontkoppeld: {REDEN}" in _toelichtingen(zac, urls["zac"], zaak, "ONTKOPPELD")
    listed = _ontkoppeld(zac, urls["zac"], zaak, document)
    assert listed, f"{document['uuid']} not in the ontkoppelde documenten of {zaak['identificatie']}"
    assert listed.get("reden") == REDEN

    moved = verplaats_document(zac, urls["zac"], document, ONTKOPPELDE_DOCUMENTEN, ander)
    expect_status(moved, HTTPStatus.NO_CONTENT, HTTPStatus.OK)
    assert document["uuid"] in _uuids(zac, urls["zac"], ander)
    assert _ontkoppeld(zac, urls["zac"], zaak, document) is None


@pytest.mark.xfail(
    strict=True,
    reason="[zac-11] ZAC 5.9.1 answers 500 to ontkoppelen without a reden after it has deleted the link in Open Zaak, "
    "so the document is on no zaak and not in the ontkoppelde documenten; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a document on a zaak in ZAC
    When the behandelaar ontkoppelt it without a reden
    Then ZAC refuses it
    And the zaak still has the document
""")
def test_ontkoppelen_without_a_reden_keeps_the_document(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """Ontkoppelen without reden answers 400 and leaves the document on the zaak."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry)
    response = ontkoppel_document(zac, urls["zac"], zaak, document, None, registry)
    kept = document["uuid"] in _uuids(zac, urls["zac"], zaak)
    if not kept:  # the zaak's cleanup no longer reaches it
        in_openzaak = f"{urls['openzaak']}/{DOCUMENTEN}/enkelvoudiginformatieobjecten/{document['uuid']}"
        registry.add(f"document {document['uuid']}", lambda: openzaak_productaanvraag.delete(in_openzaak))
    assert kept, f"ZAC answered {response.status_code} and the zaak no longer has the document"
    expect_status(response, HTTPStatus.BAD_REQUEST)


@pytest.mark.scenario("""
    Given a document ontkoppeld from a zaak in ZAC
    When the recordmanager deletes it from the ontkoppelde documenten
    Then the ontkoppelde documenten no longer list it
    And Open Zaak no longer has the document
""")
def test_ontkoppeld_document_deleted_is_gone_from_open_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """Deleting from ontkoppelde documenten deletes the document in Open Zaak's Documenten API."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry)
    expect_status(ontkoppel_document(zac, urls["zac"], zaak, document, REDEN, registry), HTTPStatus.NO_CONTENT)
    listed = _ontkoppeld(zac, urls["zac"], zaak, document)
    assert listed, f"{document['uuid']} not in the ontkoppelde documenten of {zaak['identificatie']}"
    in_openzaak = f"{urls['openzaak']}/{DOCUMENTEN}/enkelvoudiginformatieobjecten/{document['uuid']}"
    openzaak_productaanvraag.request("GET", in_openzaak, HTTPStatus.OK)

    expect_status(delete_ontkoppeld_document(zac, urls["zac"], listed), HTTPStatus.NO_CONTENT)
    assert _ontkoppeld(zac, urls["zac"], zaak, document) is None
    openzaak_productaanvraag.request("GET", in_openzaak, HTTPStatus.NOT_FOUND)


@pytest.mark.scenario("""
    Given a document on a zaak in ZAC
    When the behandelaar vergrendelt it
    Then the document shows as vergrendeld and cannot be deleted
    When the behandelaar ontgrendelt it
    Then the document can be deleted
""")
def test_locked_document_cannot_be_deleted_until_unlocked(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """A locked document has the indicatie VERGRENDELD; ZAC refuses its delete until it is unlocked."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry, status="in_bewerking")
    url = document_url(urls["zac"], document)
    of_zaak = {"zaak": str(zaak["uuid"])}
    expect_status(zac.post(f"{url}/lock", params=of_zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    # Unlocked before the zaak's cleanup deletes the document.
    registry.add(f"lock of document {document['uuid']}", lambda: zac.post(f"{url}/unlock", params=of_zaak))
    locked = expect_status(zac.get(url, params=of_zaak), HTTPStatus.OK).json()
    assert "VERGRENDELD" in strings(locked.get("indicaties"))
    reden = {"zaakUuid": zaak["uuid"], "reden": "podiumd-tests"}
    expect_status(zac.delete(url, json=reden), *REFUSED)

    expect_status(zac.post(f"{url}/unlock", params=of_zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    expect_status(zac.delete(url, json=reden), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert document["uuid"] not in _uuids(zac, urls["zac"], zaak)


@pytest.mark.scenario("""
    Given a document in bewerking on a zaak in ZAC
    When the behandelaar adds a new version with a new file, titel, beschrijving, taal and vertrouwelijkheid
    Then the document is one version further with the new file and metadata
    When the behandelaar adds a new version with only a new beschrijving
    Then the document is one more version further and keeps the file
""")
def test_nieuwe_versie_changes_the_file_and_the_metadata(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """Nieuwe versie (PUT informatieobject) with and without a file raises versie by one and keeps the given fields."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry, status="in_bewerking")
    fields: JsonObject = {
        "titel": registry.tagged("versie-2"),
        "beschrijving": "tweede versie",
        "taal": taal(zac, urls["zac"], "eng"),
        "vertrouwelijkheidaanduiding": "VERTROUWELIJK",
        "toelichting": "podiumd-tests nieuwe versie",
    }
    file = (f"{registry.tagged('versie-2')}.txt", "text/plain", b"versie 2")
    changed = nieuwe_versie(zac, urls["zac"], zaak, document, fields, file)
    version = expect_status(changed, HTTPStatus.OK).json()
    assert version["versie"] == int(str(document["versie"])) + 1
    assert (version["titel"], version["beschrijving"], version["taal"], version["vertrouwelijkheidaanduiding"]) == (
        fields["titel"],
        "tweede versie",
        "Engels",
        "VERTROUWELIJK",
    )
    assert version["bestandsnaam"] == file[0]

    metadata = nieuwe_versie(zac, urls["zac"], zaak, document, {"beschrijving": "derde versie"})
    third = expect_status(metadata, HTTPStatus.OK).json()
    assert (third["versie"], third["beschrijving"], third["titel"]) == (
        version["versie"] + 1,
        "derde versie",
        fields["titel"],
    )
    download = zac.get(f"{document_url(urls['zac'], document)}/download")
    assert expect_status(download, HTTPStatus.OK).content == b"versie 2"


@pytest.mark.scenario("""
    Given a PDF in bewerking on a zaak in ZAC
    When the behandelaar ondertekent it from the document page
    Then the document is definitief and shows as ondertekend
    And it cannot be ondertekend again
""")
def test_document_is_ondertekend_on_a_cmmn_zaak(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """Ondertekenen sets status definitief and the indicatie ONDERTEKEND; a second ondertekenen is refused."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry, suffix="pdf", status="in_bewerking")
    url = document_url(urls["zac"], document)
    of_zaak = {"zaak": str(zaak["uuid"])}
    expect_status(zac.post(f"{url}/onderteken", params=of_zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    signed = expect_status(zac.get(url, params=of_zaak), HTTPStatus.OK).json()
    assert signed["status"] == "definitief"
    assert "ONDERTEKEND" in strings(signed.get("indicaties"))
    expect_status(zac.post(f"{url}/onderteken", params=of_zaak), *REFUSED)


@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds an e-mail saved as .eml
    Then the zaak has the document and its download is the same e-mail
""")
def test_eml_document_is_kept_intact(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """A .eml upload is stored as message/rfc822 and downloads byte for byte."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry, suffix="eml")
    assert document["formaat"] == "message/rfc822"
    download = zac.get(f"{document_url(urls['zac'], document)}/download")
    assert expect_status(download, HTTPStatus.OK).content == FILES["eml"][1]


@pytest.mark.parametrize(
    ("extension", "content"),
    [
        ("aac", b"podiumd-tests"),
        ("mp3", b"podiumd-tests"),
        ("exe", b"podiumd-tests"),
        ("msi", b"podiumd-tests"),
        ("txt", b""),
    ],
    ids=["aac", "mp3", "exe", "msi", "empty"],
)
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds an audio file, a program, an installer or an empty file
    Then ZAC refuses the upload
    And the zaak has no document
""")
def test_upload_of_a_refused_file_type_or_an_empty_file_is_refused(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    registry: ResourceRegistry,
    extension: str,
    content: bytes,
) -> None:
    """ZAC answers 400 to an extension outside its allowed file types, and to an empty file."""
    zaak = zac_zaak()
    refused = upload(zac, urls["zac"], zaak, registry, extension=extension, file=("application/octet-stream", content))
    expect_status(refused, HTTPStatus.BAD_REQUEST)
    assert _uuids(zac, urls["zac"], zaak) == []


# Room for the multipart form around the file.
FORM_OVERHEAD = 64 * 1024


@pytest.mark.scenario("""
    Given ZAC's largest document upload
    When an upload of that size is announced through the platform's edge
    Then no proxy in front of ZAC refuses it as too large
""")
def test_edge_accepts_zacs_largest_upload(
    podiumd_env: Environment, zac: requests.Session, urls: dict[str, str]
) -> None:
    """The gateway, WAF and zac-nginx allow a request body of ZAC's maximum file size.

    Proxies that buffer the body first are not seen past: the probe sends only 1 KiB.
    """
    size = max_file_size_mb(zac, urls["zac"]) * 1024 * 1024 + FORM_OVERHEAD
    url = f"{urls['zac']}/rest/informatieobjecten/informatieobject/{uuid.uuid4()}/podiumd-tests"
    status = podiumd_env.announced_body_status(url, size)
    assert status != HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"the edge refuses a body of {size} bytes for {url}"
