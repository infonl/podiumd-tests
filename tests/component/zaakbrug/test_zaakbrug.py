"""ZaakBrug: ZDS 1.2 messages answer through the translate endpoints and reach Open Zaak."""

from __future__ import annotations

import base64

from dataclasses import replace
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import ZAAKBRUG_IOT
from podiumd_tests.bootstrap.names import ZAAKBRUG_VERSIES_ZAAKTYPE
from podiumd_tests.bootstrap.names import ZAAKBRUG_ZAAKTYPE
from podiumd_tests.defects import DefectSymptomError
from podiumd_tests.defects import symptom
from podiumd_tests.json_data import strings
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.zaakbrug import ZAAKBRUG_BRONORGANISATIE
from podiumd_tests.zaakbrug import ZDS
from podiumd_tests.zaakbrug import Document
from podiumd_tests.zaakbrug import ZaakVelden
from podiumd_tests.zaakbrug import actualiseer_zaakstatus
from podiumd_tests.zaakbrug import cancel_checkout
from podiumd_tests.zaakbrug import checked_out_id
from podiumd_tests.zaakbrug import document_identificatie
from podiumd_tests.zaakbrug import document_inhoud
from podiumd_tests.zaakbrug import expect_expired_version_bug
from podiumd_tests.zaakbrug import geef_lijst_zaakdocumenten
from podiumd_tests.zaakbrug import geef_zaak_details
from podiumd_tests.zaakbrug import geef_zaakdocument_bewerken
from podiumd_tests.zaakbrug import geef_zaakdocument_lezen
from podiumd_tests.zaakbrug import geef_zaken_van_initiator
from podiumd_tests.zaakbrug import genereer_document_id
from podiumd_tests.zaakbrug import is_bevestiging
from podiumd_tests.zaakbrug import is_fault
from podiumd_tests.zaakbrug import send
from podiumd_tests.zaakbrug import update_zaak
from podiumd_tests.zaakbrug import update_zaakdocument
from podiumd_tests.zaakbrug import voeg_zaakdocument_toe
from podiumd_tests.zaakbrug import zaak_identificatie
from podiumd_tests.zaakbrug import zaak_identificaties
from podiumd_tests.zaakbrug import zaakdocument_identificaties

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry
    from podiumd_tests.zaakbrug import CreatedZaak

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zaakbrug"),
    pytest.mark.usefixtures("first_identificaties"),
]

PDF = base64.b64encode(b"%PDF-1.4 ptest").decode()
MADE_HERE = pytest.mark.source(
    "podiumd-tests",
    "PodiumD 4.10 adds ZaakBrug: ZDS 1.2 messages answer through its translate endpoints and reach Open Zaak.",
)


def _attach(http: requests.Session, urls: dict[str, str], zaak: str, status: str = "In bewerking") -> str:
    """Attach a new document to the zaak with genereerDocumentIdentificatie and voegZaakdocumentToe; its identificatie."""
    now = datetime.now(UTC)
    base = urls["zaakbrug"] + ZDS
    document = document_identificatie(
        send(http, f"{base}/VrijBericht", genereer_document_id(now), "genereerDocumentIdentificatie_Di02")
    )
    assert document
    envelope = voeg_zaakdocument_toe(now, zaak, ZAAKBRUG_ZAAKTYPE, Document(document, ZAAKBRUG_IOT, PDF, status))
    assert is_bevestiging(send(http, f"{base}/OntvangAsynchroon", envelope, "voegZaakdocumentToe_Lk01"))
    return document


@pytest.mark.requires("openzaak")
@MADE_HERE
@pytest.mark.scenario("""
    Given a new zaak identificatie from ZaakBrug
    When a client sends a creeerZaak message with it to ZaakBrug
    Then ZaakBrug confirms the message
    And the zaak is in Open Zaak with ZaakBrug's RSIN as bronorganisatie and an initiator rol for a natuurlijk persoon
    And a geefZaakdetails message for the zaak answers with its identificatie
""")
def test_creeer_zaak_reaches_open_zaak(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, zaakbrug_zaak: Callable[..., CreatedZaak]
) -> None:
    """creeerZaak_Lk01 confirms (Bv03), Open Zaak has the zaak with an initiator rol, geefZaakdetails_Lv01 reads it."""
    zaak = zaakbrug_zaak()
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": zaak.url})
    assert any(r.get("betrokkeneType") == "natuurlijk_persoon" for r in rollen), "no initiator rol"
    details = geef_zaak_details(datetime.now(UTC), zaak.identificatie)
    answer = send(http, f"{urls['zaakbrug']}{ZDS}/BeantwoordVraag", details, "geefZaakdetails_Lv01")
    assert zaak_identificatie(answer) == zaak.identificatie


@pytest.mark.requires("openzaak")
@pytest.mark.source(
    "upstream Sudwest-Fryslan/OpenZaakBrug src/test/resources/ladybug/Verint KANA",
    "A KCC system (Verint KANA) lists a person's zaken with a zakLv01 that selects on the initiator.",
)
@pytest.mark.parametrize("message", ["geefZaakdetails_Lv01", "zakLv01"])
@pytest.mark.xfail(
    strict=True,
    raises=DefectSymptomError,
    reason="[zaakbrug-5] ZaakBrug 1.27.1 strips one character of the initiator's 11 prefix and answers an empty La01;"
    " the zakLv01 SOAPAction gets Fo03; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a zaak created through ZaakBrug whose initiator has a BSN no other zaak has
    When a KCC system asks ZaakBrug for the zaken of that initiator, as a ZDS or as a StUF-ZKN question
    Then the answer lists the zaak
""")
def test_zaken_of_an_initiator_are_listed(
    http: requests.Session, urls: dict[str, str], zaakbrug_zaak: Callable[..., CreatedZaak], message: str
) -> None:
    """A zakLv01 that selects on heeftAlsInitiator answers the initiator's zaken, with either SOAPAction."""
    bsn = random_bsn()
    zaak = zaakbrug_zaak(bsn=bsn)
    vraag = geef_zaken_van_initiator(datetime.now(UTC), bsn)
    with symptom():
        answer = send(http, f"{urls['zaakbrug']}{ZDS}/BeantwoordVraag", vraag, message)
        assert zaak_identificaties(answer) == [zaak.identificatie]


ZDS_TESTPLATFORM = "external softwarecatalogus.nl 20190501-Zaaksysteem-1346395-testrapportage.pdf"


@pytest.mark.requires("openzaak")
@MADE_HERE
@pytest.mark.source(ZDS_TESTPLATFORM, "geefLijstZaakdocumenten: the zaak's documents are listed.")
@pytest.mark.source(ZDS_TESTPLATFORM, "geefZaakdocumentLezen: a document is read with its inhoud.")
@pytest.mark.scenario("""
    Given a zaak created through ZaakBrug
    When a client attaches a document to the zaak with a voegZaakdocumentToe message
    Then ZaakBrug confirms the message and Open Zaak links the document to the zaak
    And a geefLijstZaakdocumenten message for the zaak lists the document
    And a geefZaakdocumentLezen message for the document answers its inhoud
""")
def test_voeg_zaakdocument_toe_attaches_a_document(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, zaakbrug_zaak: Callable[..., CreatedZaak]
) -> None:
    """voegZaakdocumentToe_Lk01 links a document in Open Zaak; geefLijstZaakdocumenten and geefZaakdocumentLezen read it."""
    zaak = zaakbrug_zaak()
    document = _attach(http, urls, zaak.identificatie)
    links = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": zaak.url})
    assert links, f"no zaakinformatieobject on {zaak.identificatie} after voegZaakdocumentToe"
    beantwoord = f"{urls['zaakbrug']}{ZDS}/BeantwoordVraag"
    lijst = geef_lijst_zaakdocumenten(datetime.now(UTC), zaak.identificatie)
    answer = send(http, beantwoord, lijst, "geefLijstZaakdocumenten_Lv01")
    assert zaakdocument_identificaties(answer) == [document]
    lezen = geef_zaakdocument_lezen(datetime.now(UTC), document)
    assert document_inhoud(send(http, beantwoord, lezen, "geefZaakdocumentLezen_Lv01")) == PDF


SOAPUI = "upstream wearefrank/zaakbrug e2e/SoapUI/zaakbrug-e2e-soapui-project.xml"
CREATED = ZaakVelden(kenmerk="K-1", verlenging=(5, "Eerste"))


def _update(http: requests.Session, urls: dict[str, str], zaak: str, old: ZaakVelden, new: ZaakVelden) -> None:
    envelope = update_zaak(datetime.now(UTC), zaak, ZAAKBRUG_ZAAKTYPE, old=old, new=new)
    assert is_bevestiging(send(http, f"{urls['zaakbrug']}{ZDS}/OntvangAsynchroon", envelope, "updateZaak_Lk01"))


@pytest.mark.requires("openzaak")
@pytest.mark.source(SOAPUI, "ValidVerlengingShouldBeReturnedInGeefZaakDetails: a changed verlenging is stored.")
@pytest.mark.source(SOAPUI, "ValidKenmerkenShouldBeReturnedInGeefZaakDetails: a changed kenmerk is stored.")
@pytest.mark.scenario("""
    When a client creates a zaak through ZaakBrug with a kenmerk and a verlenging
    Then Open Zaak stores the kenmerk and the verlenging
    When the client sends an updateZaak message with another kenmerk and verlenging
    Then ZaakBrug confirms the message
    And Open Zaak holds the new kenmerk and verlenging
""")
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
@pytest.mark.scenario("""
    Given a zaak created through ZaakBrug with a verlenging
    When a client sends an updateZaak message with a verlenging of duur 0 or without reden
    Then ZaakBrug confirms the message
    And the zaak in Open Zaak keeps its first verlenging
""")
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
@pytest.mark.scenario("""
    Given a zaak created through ZaakBrug
    When a client sets a first status with an actualiseerZaakstatus message
    Then ZaakBrug confirms the message
    When the client sets a second status with the same datumStatusGezet
    Then ZaakBrug answers with a SOAP Fault
    And the zaak in Open Zaak has one status
""")
def test_status_at_an_existing_datum_status_gezet_is_refused(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, zaakbrug_zaak: Callable[..., CreatedZaak]
) -> None:
    """actualiseerZaakstatus_Lk01 sets status 1; a status 2 with the same datumStatusGezet gets a SOAP Fault."""
    zaak = zaakbrug_zaak()
    gezet = datetime.now(UTC).replace(microsecond=0)
    endpoint = f"{urls['zaakbrug']}{ZDS}/OntvangAsynchroon"

    def status(volgnummer: int, omschrijving: str) -> str:
        envelope = actualiseer_zaakstatus(
            datetime.now(UTC),
            zaak.identificatie,
            ZAAKBRUG_ZAAKTYPE,
            volgnummer=volgnummer,
            omschrijving=omschrijving,
            gezet=gezet,
        )
        return send(http, endpoint, envelope, "actualiseerZaakstatus_Lk01")

    assert is_bevestiging(status(1, "Ingediend"))
    assert is_fault(status(2, "In behandeling"))
    assert len(openzaak.list(f"{ZAKEN}/statussen", {"zaak": zaak.url})) == 1


@pytest.mark.requires("openzaak")
@pytest.mark.source(
    SOAPUI, "UpdateZaakDocumentShouldNotBeAllowedIfDocumentStatusIsDefinitief: a definitief document is not updated."
)
@pytest.mark.scenario("""
    Given a zaak created through ZaakBrug
    And a document with status Definitief attached to it through ZaakBrug
    When a client checks the document out and changes its titel with an updateZaakdocument message
    Then ZaakBrug answers with a SOAP Fault
    And no document of the zaak in Open Zaak has the changed titel
""")
def test_definitief_document_is_not_updated(
    http: requests.Session, urls: dict[str, str], openzaak: ApiClient, zaakbrug_zaak: Callable[..., CreatedZaak]
) -> None:
    """A document attached as Definitief can be checked out, but updateZaakdocument_Di02 faults; its titel stays."""
    now = datetime.now(UTC)
    vrij = f"{urls['zaakbrug']}{ZDS}/VrijBericht"
    zaak = zaakbrug_zaak()
    document = _attach(http, urls, zaak.identificatie, status="Definitief")
    checked_out = checked_out_id(
        send(http, vrij, geef_zaakdocument_bewerken(now, document), "geefZaakdocumentbewerken_Di02")
    )
    assert checked_out
    update = update_zaakdocument(now, zaak.identificatie, document, checked_out, titel="gewijzigd door podiumd-tests")
    try:
        assert is_fault(send(http, vrij, update, "updateZaakdocument_Di02"))
    finally:
        send(http, vrij, cancel_checkout(now, document, checked_out), "cancelCheckout_Di02")
    links = openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": zaak.url})
    titels = [str(openzaak.get(str(link["informatieobject"]))["titel"]) for link in links]
    assert "gewijzigd door podiumd-tests" not in titels


@pytest.mark.requires("openzaak")
@pytest.mark.source(
    f"{SOAPUI} 10-TestSuite-ZaakTypeVersions",
    "ActualiseerZaakstatusOnZaakWithExpiredZaakTypeVersionShouldUseStatusTypeOfThatVersion: the zaak's own version.",
)
@pytest.mark.scenario("""
    Given a zaaktype with a version valid in 2020 and a newer version from 2021
    And a zaak of the 2020 version in Open Zaak
    When a client sets the zaak's first status with an actualiseerZaakstatus message to ZaakBrug
    Then ZaakBrug confirms the message
    And the zaak's status in Open Zaak has a statustype of the 2020 version
""")
def test_status_on_an_expired_zaaktype_version_uses_that_versions_statustype(
    http: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
) -> None:
    """ZaakBrug takes the statustype from the zaak's zaaktype version, not from the version valid today."""
    expect_expired_version_bug(request, podiumd_env)
    need_bootstrap("openzaak-zaaktype-zaakbrug-versies")
    versions = openzaak.list(f"{CATALOGI}/zaaktypen", {"identificatie": ZAAKBRUG_VERSIES_ZAAKTYPE})
    expired = next(v for v in versions if v.get("eindeGeldigheid"))
    zaak = make_zaak(
        openzaak, registry, str(expired["url"]), startdatum="2020-06-01", bronorganisatie=ZAAKBRUG_BRONORGANISATIE
    )
    envelope = actualiseer_zaakstatus(
        datetime.now(UTC),
        str(zaak["identificatie"]),
        ZAAKBRUG_VERSIES_ZAAKTYPE,
        volgnummer=1,
        omschrijving="Ingediend v1",
        gezet=datetime.now(UTC).replace(microsecond=0),
    )
    with symptom():
        assert is_bevestiging(
            send(http, f"{urls['zaakbrug']}{ZDS}/OntvangAsynchroon", envelope, "actualiseerZaakstatus_Lk01")
        )
        statussen = openzaak.list(f"{ZAKEN}/statussen", {"zaak": str(zaak["url"])})
        of_version = strings(expired.get("statustypen"))
        assert [s["statustype"] for s in statussen if s["statustype"] not in of_version] == []
    assert statussen, f"no status on {zaak['identificatie']}"
