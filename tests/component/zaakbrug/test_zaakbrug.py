"""ZaakBrug: ZDS 1.2 messages answer through the translate endpoints and reach Open Zaak."""

from __future__ import annotations

import base64

from dataclasses import replace
from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import NamedTuple

import pytest

from podiumd_tests.bootstrap.names import ZAAKBRUG_IOT
from podiumd_tests.bootstrap.names import ZAAKBRUG_ZAAKTYPE
from podiumd_tests.lock import file_lock
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.zaakbrug import NO_VELDEN
from podiumd_tests.zaakbrug import ZDS
from podiumd_tests.zaakbrug import Document
from podiumd_tests.zaakbrug import ZaakVelden
from podiumd_tests.zaakbrug import actualiseer_zaakstatus
from podiumd_tests.zaakbrug import cancel_checkout
from podiumd_tests.zaakbrug import checked_out_id
from podiumd_tests.zaakbrug import creeer_zaak
from podiumd_tests.zaakbrug import document_identificatie
from podiumd_tests.zaakbrug import geef_zaak_details
from podiumd_tests.zaakbrug import geef_zaakdocument_bewerken
from podiumd_tests.zaakbrug import genereer_document_identificatie
from podiumd_tests.zaakbrug import genereer_zaak_identificatie
from podiumd_tests.zaakbrug import is_bevestiging
from podiumd_tests.zaakbrug import is_fault
from podiumd_tests.zaakbrug import soap_action
from podiumd_tests.zaakbrug import update_zaak
from podiumd_tests.zaakbrug import update_zaakdocument
from podiumd_tests.zaakbrug import voeg_zaakdocument_toe
from podiumd_tests.zaakbrug import zaak_identificatie

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zaakbrug"),
]

# ZaakBrug maps gemeentecode 1900 to this RSIN (zaakbrug.globals.organizations); the zaak's bronorganisatie.
ZAAKBRUG_BRONORGANISATIE = "823288444"
INITIATOR_BSN = "111111110"
MADE_HERE = pytest.mark.source(
    "podiumd-tests",
    "PodiumD 4.10 adds ZaakBrug: ZDS 1.2 messages answer through its translate endpoints and reach Open Zaak.",
)


@pytest.fixture(scope="module", autouse=True, name="first_identificaties")
def fixture_first_identificaties(http: requests.Session, urls: dict[str, str], run_dir: Path) -> None:
    """The run's first genereer calls, one worker at a time: parallel first calls break ZaakBrug's counter (zaakbrug-2)."""
    done = run_dir / "zaakbrug-identificaties"
    with file_lock(run_dir / "zaakbrug-identificaties.lock"):
        if done.exists():
            return
        now, url = datetime.now(UTC), urls["zaakbrug"] + ZDS + "/VrijBericht"
        _post(http, url, genereer_zaak_identificatie(now), "genereerZaakIdentificatie_Di02")
        _post(http, url, genereer_document_identificatie(now), "genereerDocumentIdentificatie_Di02")
        done.touch()


def _post(http: requests.Session, url: str, envelope: str, message: str) -> str:
    return expect_status(http.post(url, data=envelope, headers=soap_action(message)), HTTPStatus.OK).text


@MADE_HERE
def test_genereer_zaak_identificatie(http: requests.Session, urls: dict[str, str]) -> None:
    """genereerZaakIdentificatie_Di02 answers a new zaak identificatie (stored in ZaakBrug, not in Open Zaak)."""
    answer = _post(
        http,
        urls["zaakbrug"] + ZDS + "/VrijBericht",
        genereer_zaak_identificatie(datetime.now(UTC)),
        "genereerZaakIdentificatie_Di02",
    )
    assert zaak_identificatie(answer)


class CreatedZaak(NamedTuple):
    """A zaak created through ZaakBrug: its identificatie and its URL in Open Zaak."""

    identificatie: str
    url: str


@pytest.fixture(name="zaakbrug_zaak")
def fixture_zaakbrug_zaak(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, registry: ResourceRegistry
) -> Callable[..., CreatedZaak]:
    """Create a zaak through genereerZaakIdentificatie and creeerZaak (Bv03); cleanup deletes it with its documents."""

    def create(velden: ZaakVelden = NO_VELDEN) -> CreatedZaak:
        now = datetime.now(UTC)
        base = urls["zaakbrug"] + ZDS
        zaak = zaak_identificatie(
            _post(http, base + "/VrijBericht", genereer_zaak_identificatie(now), "genereerZaakIdentificatie_Di02")
        )
        assert zaak
        envelope = creeer_zaak(now, zaak, ZAAKBRUG_ZAAKTYPE, INITIATOR_BSN, velden=velden)
        assert is_bevestiging(_post(http, base + "/OntvangAsynchroon", envelope, "creeerZaak_Lk01"))
        found = openzaak.list(f"{ZAKEN}/zaken", {"identificatie": zaak, "bronorganisatie": ZAAKBRUG_BRONORGANISATIE})
        assert found, f"no zaak {zaak} in Open Zaak after creeerZaak"
        url = str(found[0]["url"])
        registry.add(f"zaakbrug zaak {zaak}", lambda: delete_zaak(openzaak, url, with_documents=True))
        return CreatedZaak(zaak, url)

    return create


@pytest.mark.requires("openzaak")
@MADE_HERE
def test_creeer_zaak_reaches_open_zaak(openzaak: ApiClient, zaakbrug_zaak: Callable[..., CreatedZaak]) -> None:
    """creeerZaak_Lk01 confirms (Bv03) and the zaak is in Open Zaak with the ZaakBrug RSIN and an initiator rol."""
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": zaakbrug_zaak().url})
    assert any(r.get("betrokkeneType") == "natuurlijk_persoon" for r in rollen), "no initiator rol"


@pytest.mark.requires("openzaak")
@MADE_HERE
def test_geef_zaak_details_reads_a_created_zaak(
    http: requests.Session, urls: dict[str, str], zaakbrug_zaak: Callable[..., CreatedZaak]
) -> None:
    """geefZaakdetails_Lv01 reads back a zaak created through creeerZaak (La01 carries its identificatie)."""
    zaak = zaakbrug_zaak().identificatie
    details = geef_zaak_details(datetime.now(UTC), zaak)
    answer = _post(http, urls["zaakbrug"] + ZDS + "/BeantwoordVraag", details, "geefZaakdetails_Lv01")
    assert zaak_identificatie(answer) == zaak


@pytest.mark.requires("openzaak")
@MADE_HERE
def test_voeg_zaakdocument_toe_attaches_a_document(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, zaakbrug_zaak: Callable[..., CreatedZaak]
) -> None:
    """voegZaakdocumentToe_Lk01 attaches a document to a ZaakBrug zaak: Open Zaak links it as a zaakdocument."""
    now = datetime.now(UTC)
    base = urls["zaakbrug"] + ZDS
    zaak = zaakbrug_zaak()
    document = document_identificatie(
        _post(http, base + "/VrijBericht", genereer_document_identificatie(now), "genereerDocumentIdentificatie_Di02")
    )
    assert document
    pdf = base64.b64encode(b"%PDF-1.4 ptest").decode()
    envelope = voeg_zaakdocument_toe(now, zaak.identificatie, ZAAKBRUG_ZAAKTYPE, Document(document, ZAAKBRUG_IOT, pdf))
    assert is_bevestiging(_post(http, base + "/OntvangAsynchroon", envelope, "voegZaakdocumentToe_Lk01"))
    links = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": zaak.url})
    assert links, f"no zaakinformatieobject on {zaak.identificatie} after voegZaakdocumentToe"


SOAPUI = "upstream wearefrank/zaakbrug e2e/SoapUI/zaakbrug-e2e-soapui-project.xml"
CREATED = ZaakVelden(kenmerk="K-1", verlenging=(5, "Eerste"))


def _update(http: requests.Session, urls: dict[str, str], zaak: str, old: ZaakVelden, new: ZaakVelden) -> None:
    envelope = update_zaak(datetime.now(UTC), zaak, ZAAKBRUG_ZAAKTYPE, old=old, new=new)
    assert is_bevestiging(_post(http, urls["zaakbrug"] + ZDS + "/OntvangAsynchroon", envelope, "updateZaak_Lk01"))


@pytest.mark.requires("openzaak")
@pytest.mark.source(SOAPUI, "ValidVerlengingShouldBeReturnedInGeefZaakDetails: a changed verlenging is stored.")
@pytest.mark.source(SOAPUI, "ValidKenmerkenShouldBeReturnedInGeefZaakDetails: a changed kenmerk is stored.")
def test_update_zaak_changes_verlenging_and_kenmerk(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, zaakbrug_zaak: Callable[..., CreatedZaak]
) -> None:
    """creeerZaak stores a kenmerk and verlenging in Open Zaak; updateZaak_Lk01 replaces both."""
    zaak = zaakbrug_zaak(CREATED)
    created = openzaak.get(zaak.url)
    assert (created["verlenging"], created["kenmerken"]) == (
        {"duur": "P5D", "reden": "Eerste"},
        [{"kenmerk": "K-1", "bron": "ptest"}],
    )
    _update(http, urls, zaak.identificatie, CREATED, ZaakVelden(kenmerk="K-2", verlenging=(10, "Changed")))
    changed = openzaak.get(zaak.url)
    assert (changed["verlenging"], changed["kenmerken"]) == (
        {"duur": "P10D", "reden": "Changed"},
        [{"kenmerk": "K-2", "bron": "ptest"}],
    )


@pytest.mark.requires("openzaak")
@pytest.mark.parametrize(
    "verlenging",
    [
        pytest.param(
            (0, "Nul"),
            id="duur-0",
            marks=pytest.mark.source(SOAPUI, "VerlengingWithDuurZeroShouldBeIgnored: duur 0 leaves the verlenging."),
        ),
        pytest.param(
            (7, ""),
            id="empty-reden",
            marks=pytest.mark.source(
                SOAPUI, "VerlengingWithEmptyRedenShouldBeIgnored: an empty reden leaves the verlenging."
            ),
        ),
    ],
)
def test_update_zaak_ignores_an_incomplete_verlenging(
    http: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    zaakbrug_zaak: Callable[..., CreatedZaak],
    verlenging: tuple[int, str],
) -> None:
    """updateZaak_Lk01 with a verlenging of duur 0 or without reden confirms and keeps the zaak's verlenging."""
    zaak = zaakbrug_zaak(CREATED)
    _update(http, urls, zaak.identificatie, CREATED, replace(CREATED, verlenging=verlenging))
    assert openzaak.get(zaak.url)["verlenging"] == {"duur": "P5D", "reden": "Eerste"}


@pytest.mark.requires("openzaak")
@pytest.mark.source(
    SOAPUI,
    "NewStatusWithAlreadyExistingDatumstatusgezetShouldThrowTechnicalError: a second status at the same moment faults.",
)
def test_status_at_an_existing_datum_status_gezet_is_refused(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, zaakbrug_zaak: Callable[..., CreatedZaak]
) -> None:
    """actualiseerZaakstatus_Lk01 sets status 1; a status 2 with the same datumStatusGezet gets a SOAP Fault."""
    zaak = zaakbrug_zaak()
    gezet = datetime.now(UTC).replace(microsecond=0)
    endpoint = urls["zaakbrug"] + ZDS + "/OntvangAsynchroon"

    def status(volgnummer: int, omschrijving: str) -> str:
        envelope = actualiseer_zaakstatus(
            datetime.now(UTC),
            zaak.identificatie,
            ZAAKBRUG_ZAAKTYPE,
            volgnummer=volgnummer,
            omschrijving=omschrijving,
            gezet=gezet,
        )
        return _post(http, endpoint, envelope, "actualiseerZaakstatus_Lk01")

    assert is_bevestiging(status(1, "Ingediend"))
    assert is_fault(status(2, "In behandeling"))
    assert len(openzaak.list(f"{ZAKEN}/statussen", {"zaak": zaak.url})) == 1


@pytest.mark.requires("openzaak")
@pytest.mark.source(
    SOAPUI, "UpdateZaakDocumentShouldNotBeAllowedIfDocumentStatusIsDefinitief: a definitief document is not updated."
)
def test_definitief_document_is_not_updated(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, zaakbrug_zaak: Callable[..., CreatedZaak]
) -> None:
    """A document attached as Definitief can be checked out, but updateZaakdocument_Di02 faults; its titel stays."""
    now = datetime.now(UTC)
    vrij = urls["zaakbrug"] + ZDS + "/VrijBericht"
    zaak = zaakbrug_zaak()
    document = document_identificatie(
        _post(http, vrij, genereer_document_identificatie(now), "genereerDocumentIdentificatie_Di02")
    )
    assert document
    pdf = base64.b64encode(b"%PDF-1.4 ptest").decode()
    toe = voeg_zaakdocument_toe(
        now, zaak.identificatie, ZAAKBRUG_ZAAKTYPE, Document(document, ZAAKBRUG_IOT, pdf, status="Definitief")
    )
    assert is_bevestiging(_post(http, urls["zaakbrug"] + ZDS + "/OntvangAsynchroon", toe, "voegZaakdocumentToe_Lk01"))
    checked_out = checked_out_id(
        _post(http, vrij, geef_zaakdocument_bewerken(now, document), "geefZaakdocumentbewerken_Di02")
    )
    assert checked_out
    try:
        update = update_zaakdocument(
            now, zaak.identificatie, document, checked_out, titel="gewijzigd door podiumd-tests"
        )
        assert is_fault(_post(http, vrij, update, "updateZaakdocument_Di02"))
    finally:
        _post(http, vrij, cancel_checkout(now, document, checked_out), "cancelCheckout_Di02")
    links = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": zaak.url})
    titels = [str(openzaak.get(str(link["informatieobject"]))["titel"]) for link in links]
    assert "gewijzigd door podiumd-tests" not in titels
