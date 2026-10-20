"""ZaakBrug: ZDS 1.2 messages answer through the translate endpoints and reach Open Zaak."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import ZAAKBRUG_IOT
from podiumd_tests.bootstrap.names import ZAAKBRUG_ZAAKTYPE
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.zaakbrug import ZDS
from podiumd_tests.zaakbrug import Document
from podiumd_tests.zaakbrug import creeer_zaak
from podiumd_tests.zaakbrug import document_identificatie
from podiumd_tests.zaakbrug import geef_zaak_details
from podiumd_tests.zaakbrug import genereer_document_identificatie
from podiumd_tests.zaakbrug import genereer_zaak_identificatie
from podiumd_tests.zaakbrug import is_bevestiging
from podiumd_tests.zaakbrug import soap_action
from podiumd_tests.zaakbrug import voeg_zaakdocument_toe
from podiumd_tests.zaakbrug import zaak_identificatie

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zaakbrug")]

# ZaakBrug maps gemeentecode 1900 to this RSIN (zaakbrug.globals.organizations); the zaak's bronorganisatie.
ZAAKBRUG_BRONORGANISATIE = "823288444"
INITIATOR_BSN = "111111110"


def _post(http: requests.Session, url: str, envelope: str, message: str) -> str:
    return expect_status(http.post(url, data=envelope, headers=soap_action(message)), HTTPStatus.OK).text


def test_genereer_zaak_identificatie(http: requests.Session, urls: dict[str, str]) -> None:
    """genereerZaakIdentificatie_Di02 answers a new zaak identificatie (stored in ZaakBrug, not in Open Zaak)."""
    answer = _post(
        http,
        urls["zaakbrug"] + ZDS + "/VrijBericht",
        genereer_zaak_identificatie(datetime.now(UTC)),
        "genereerZaakIdentificatie_Di02",
    )
    assert zaak_identificatie(answer)


@pytest.mark.requires("openzaak")
def test_creeer_zaak_reaches_open_zaak(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, registry: ResourceRegistry
) -> None:
    """creeerZaak_Lk01 confirms (Bv03) and the zaak is in Open Zaak with the ZaakBrug RSIN and an initiator rol."""
    now = datetime.now(UTC)
    base = urls["zaakbrug"] + ZDS
    zaak = zaak_identificatie(
        _post(http, base + "/VrijBericht", genereer_zaak_identificatie(now), "genereerZaakIdentificatie_Di02")
    )
    assert zaak
    envelope = creeer_zaak(now, zaak, ZAAKBRUG_ZAAKTYPE, INITIATOR_BSN)
    assert is_bevestiging(_post(http, base + "/OntvangAsynchroon", envelope, "creeerZaak_Lk01"))
    found = openzaak.list(f"{ZAKEN}/zaken", {"identificatie": zaak, "bronorganisatie": ZAAKBRUG_BRONORGANISATIE})
    assert found, f"no zaak {zaak} in Open Zaak after creeerZaak"
    registry.add(f"zaakbrug zaak {zaak}", lambda: delete_zaak(openzaak, str(found[0]["url"])))
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": str(found[0]["url"])})
    assert any(r.get("betrokkeneType") == "natuurlijk_persoon" for r in rollen), "no initiator rol"


@pytest.mark.requires("openzaak")
def test_geef_zaak_details_reads_a_created_zaak(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, registry: ResourceRegistry
) -> None:
    """geefZaakdetails_Lv01 reads back a zaak created through creeerZaak (La01 carries its identificatie)."""
    now = datetime.now(UTC)
    base = urls["zaakbrug"] + ZDS
    zaak = zaak_identificatie(
        _post(http, base + "/VrijBericht", genereer_zaak_identificatie(now), "genereerZaakIdentificatie_Di02")
    )
    assert zaak
    assert is_bevestiging(
        _post(
            http,
            base + "/OntvangAsynchroon",
            creeer_zaak(now, zaak, ZAAKBRUG_ZAAKTYPE, INITIATOR_BSN),
            "creeerZaak_Lk01",
        )
    )
    found = openzaak.list(f"{ZAKEN}/zaken", {"identificatie": zaak, "bronorganisatie": ZAAKBRUG_BRONORGANISATIE})
    assert found
    registry.add(f"zaakbrug zaak {zaak}", lambda: delete_zaak(openzaak, str(found[0]["url"])))
    answer = _post(http, base + "/BeantwoordVraag", geef_zaak_details(now, zaak), "geefZaakdetails_Lv01")
    assert zaak_identificatie(answer) == zaak


@pytest.mark.requires("openzaak")
def test_voeg_zaakdocument_toe_attaches_a_document(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, registry: ResourceRegistry
) -> None:
    """voegZaakdocumentToe_Lk01 attaches a document to a ZaakBrug zaak: Open Zaak links it as a zaakdocument."""
    import base64  # only this test builds a document body

    now = datetime.now(UTC)
    base = urls["zaakbrug"] + ZDS
    zaak = zaak_identificatie(
        _post(http, base + "/VrijBericht", genereer_zaak_identificatie(now), "genereerZaakIdentificatie_Di02")
    )
    assert zaak
    assert is_bevestiging(
        _post(
            http,
            base + "/OntvangAsynchroon",
            creeer_zaak(now, zaak, ZAAKBRUG_ZAAKTYPE, INITIATOR_BSN),
            "creeerZaak_Lk01",
        )
    )
    found = openzaak.list(f"{ZAKEN}/zaken", {"identificatie": zaak, "bronorganisatie": ZAAKBRUG_BRONORGANISATIE})
    assert found
    registry.add(f"zaakbrug zaak {zaak}", lambda: delete_zaak(openzaak, str(found[0]["url"]), with_documents=True))
    document = document_identificatie(
        _post(http, base + "/VrijBericht", genereer_document_identificatie(now), "genereerDocumentIdentificatie_Di02")
    )
    assert document
    pdf = base64.b64encode(b"%PDF-1.4 ptest").decode()
    envelope = voeg_zaakdocument_toe(now, zaak, ZAAKBRUG_ZAAKTYPE, Document(document, ZAAKBRUG_IOT, pdf))
    assert is_bevestiging(_post(http, base + "/OntvangAsynchroon", envelope, "voegZaakdocumentToe_Lk01"))
    links = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(found[0]["url"])})
    assert links, f"no zaakinformatieobject on {zaak} after voegZaakdocumentToe"
