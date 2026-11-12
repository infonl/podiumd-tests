"""ZAC: what a document added to a zaak keeps (metadata, vertrouwelijkheid, size), its conversion and its historie.

The zaak is of the zaaktype ZAC handles productaanvragen for; the test admin is ZAC beheerder of every domain.
"""

from __future__ import annotations

from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.zac_documents import FILES
from podiumd_tests.zac_documents import document_historie
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import documenttypen
from podiumd_tests.zac_documents import form_date
from podiumd_tests.zac_documents import max_file_size_mb
from podiumd_tests.zac_documents import nieuwe_versie
from podiumd_tests.zac_documents import taal
from podiumd_tests.zac_documents import upload
from podiumd_tests.zac_documents import upload_of_size
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_documents import zaak_documents

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
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

# The vertrouwelijkheidaanduidingen of the ZGW APIs, as ZAC's document form sends them.
VERTROUWELIJKHEIDAANDUIDINGEN = (
    "OPENBAAR",
    "BEPERKT_OPENBAAR",
    "INTERN",
    "ZAAKVERTROUWELIJK",
    "VERTROUWELIJK",
    "CONFIDENTIEEL",
    "GEHEIM",
    "ZEER_GEHEIM",
)


@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds a document with diacritics and an emoji in its titel, beschrijving and auteur, in English
    Then the zaak's document has that titel, beschrijving, auteur and taal
""")
def test_uploaded_document_keeps_its_metadata(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """Titel, beschrijving, auteur and taal of an upload are stored as sent, in UTF-8."""
    zaak = zac_zaak()
    fields = {
        "titel": registry.tagged("Één café € ü ß ø 😀"),
        "beschrijving": "naïef résumé",
        "auteur": "Zoë Ångström",
        "taal": "eng",
    }
    document = uploaded_document(zac, urls["zac"], zaak, registry, taak=None, **fields)
    listed = next(item for item in zaak_documents(zac, urls["zac"], zaak) if item.get("uuid") == document["uuid"])
    stored = {name: listed.get(name) for name in fields}
    assert stored == {**fields, "taal": taal(zac, urls["zac"], "eng")["naam"]}


@pytest.mark.scenario("""
    Given a zaak in ZAC
    Then ZAC offers the documenttypen of the zaak's zaaktype in Open Zaak, each with its vertrouwelijkheidaanduiding
    When the behandelaar adds a document with each of the eight vertrouwelijkheidaanduidingen
    Then each document keeps the one it was given
""")
def test_document_has_one_of_the_eight_vertrouwelijkheidaanduidingen(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """The documenttypen match Open Zaak's informatieobjecttypen of the zaaktype; each ZGW value is stored."""
    zaak = zac_zaak()
    offered = {
        str(item.get("omschrijving")): item.get("vertrouwelijkheidaanduiding")
        for item in documenttypen(zac, urls["zac"], zaak)
    }
    zaaktype_uuid = section(zaak, "zaaktype")["uuid"]
    zaaktype = openzaak.get(f"{urls['openzaak']}/{CATALOGI}/zaaktypen/{zaaktype_uuid}")
    in_openzaak = [openzaak.get(url) for url in strings(zaaktype.get("informatieobjecttypen"))]
    assert offered == {str(iot["omschrijving"]): str(iot["vertrouwelijkheidaanduiding"]).upper() for iot in in_openzaak}

    stored = [
        uploaded_document(zac, urls["zac"], zaak, registry, vertrouwelijkheidaanduiding=value).get(
            "vertrouwelijkheidaanduiding"
        )
        for value in VERTROUWELIJKHEIDAANDUIDINGEN
    ]
    assert tuple(stored) == VERTROUWELIJKHEIDAANDUIDINGEN


@pytest.mark.xfail(
    strict=True,
    reason="[zac-28] ZAC 5.9.1 answers 500 to an upload whose vertrouwelijkheidaanduiding is none of its enum "
    "constants; not yet reported upstream",
)
@pytest.mark.parametrize("value", ["openbaar", "SUPERGEHEIM"])
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds a document whose vertrouwelijkheidaanduiding is in lower case or unknown
    Then ZAC refuses it as a bad request
    And the zaak has no document
""")
def test_document_with_another_vertrouwelijkheidaanduiding_is_refused(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    registry: ResourceRegistry,
    value: str,
) -> None:
    """An upload with a vertrouwelijkheidaanduiding outside the eight upper-case values answers 400."""
    zaak = zac_zaak()
    response = upload(
        zac, urls["zac"], zaak, registry, extension="txt", file=FILES["txt"], vertrouwelijkheidaanduiding=value
    )
    expect_status(response, HTTPStatus.BAD_REQUEST)
    assert zaak_documents(zac, urls["zac"], zaak) == []


@pytest.mark.parametrize("status", ["in_bewerking", "ter_vaststelling"])
@pytest.mark.scenario("""
    Given a Word document on a zaak in ZAC that is not yet definitief
    When the behandelaar converts it to PDF
    Then ZAC refuses it
""")
def test_document_that_is_not_definitief_is_not_converted(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    registry: ResourceRegistry,
    status: str,
) -> None:
    """Converting a document in bewerking or ter vaststelling is refused (policy converteren)."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry, suffix="word", status=status)
    converted = zac.post(f"{document_url(urls['zac'], document)}/convert", params={"zaak": str(zaak["uuid"])})
    expect_status(converted, *REFUSED)


@pytest.mark.scenario("""
    Given a Word document in bewerking on a zaak in ZAC
    When the behandelaar adds a definitief version, converts it to PDF and ondertekent it
    Then the document's historie shows each step with its time, its user and its reason
    And the conversion from the Word file name to the PDF file name
""")
def test_document_historie_shows_versie_conversion_and_ondertekening(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """Open Zaak's audittrail of the document, as ZAC shows it: toelichting, door, datumTijd and bestandsnaam."""
    start = datetime.now(tz=UTC).replace(microsecond=0)
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry, suffix="word", status="in_bewerking")
    url = document_url(urls["zac"], document)
    of_zaak = {"zaak": str(zaak["uuid"])}
    versie = {"status": "definitief", "toelichting": "podiumd-tests definitief"}
    expect_status(nieuwe_versie(zac, urls["zac"], zaak, document, versie), HTTPStatus.OK)
    expect_status(zac.post(f"{url}/convert", params=of_zaak, timeout=60), HTTPStatus.NO_CONTENT, HTTPStatus.OK)
    expect_status(zac.post(f"{url}/onderteken", params=of_zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    historie = document_historie(zac, urls["zac"], document)

    reasons = {str(line.get("toelichting")) for line in historie}
    assert {"podiumd-tests definitief", "Geconverteerd naar PDF", "Door ondertekenen"} <= reasons, reasons
    renamed = [
        (line.get("oudeWaarde"), line.get("nieuweWaarde"))
        for line in historie
        if line.get("attribuutLabel") == "bestandsnaam"
    ]
    name = str(document["bestandsnaam"]).removesuffix(".docx")
    assert (f"{name}.docx", f"{name}.pdf") in renamed
    end = datetime.now(tz=UTC)
    for line in historie:
        assert start <= datetime.fromisoformat(str(line["datumTijd"])) <= end, line
        assert line.get("door"), line


# Sends MAX_FILE_SIZE_MB through the edge: a proxy that holds the body in memory can run out of it.
@pytest.mark.destructive
@pytest.mark.slow
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds a document one byte larger than ZAC's maximum file size
    Then ZAC refuses it as too large
    And the zaak has no document
""")
def test_document_above_the_maximum_file_size_is_refused(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """An upload of MAX_FILE_SIZE_MB plus one byte answers 413 msg.error.file.size-exceeded; the zaak has no document."""
    zaak = zac_zaak()
    size = max_file_size_mb(zac, urls["zac"]) * 1024 * 1024 + 1
    refused = upload_of_size(zac, urls["zac"], zaak, registry, size)
    assert "msg.error.file.size-exceeded" in expect_status(refused, HTTPStatus.REQUEST_ENTITY_TOO_LARGE).text
    assert zaak_documents(zac, urls["zac"], zaak) == []


@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds a received document, with an ontvangstdatum, in bewerking or ter vaststelling
    Then ZAC refuses it
    When the behandelaar adds it as definitief
    Then the zaak has the document with its ontvangstdatum
""")
def test_received_document_is_definitief(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """Open Zaak refuses status in_bewerking and ter_vaststelling with an ontvangstdatum (400); definitief is stored."""
    zaak = zac_zaak()
    received = date.today() - timedelta(days=1)  # noqa: DTZ011  # ZAC's local date
    for status in ("in_bewerking", "ter_vaststelling"):
        refused = upload(
            zac,
            urls["zac"],
            zaak,
            registry,
            extension="txt",
            file=FILES["txt"],
            ontvangstdatum=form_date(received),
            status=status,
        )
        expect_status(refused, HTTPStatus.BAD_REQUEST)
    document = uploaded_document(zac, urls["zac"], zaak, registry, ontvangstdatum=form_date(received))
    assert (document["status"], document["ontvangstdatum"]) == ("definitief", received.isoformat())
