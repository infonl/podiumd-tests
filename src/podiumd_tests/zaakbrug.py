"""ZaakBrug: ZDS 1.2 (StUF-ZKN 3.10) SOAP calls that it translates to the ZGW APIs."""

from __future__ import annotations

import uuid

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import NamedTuple
from xml.etree.ElementTree import fromstring  # nosec B405  # parses ZaakBrug's own answer
from xml.sax.saxutils import quoteattr  # nosec B406  # escapes, parses nothing

from podiumd_tests.workloads import expect_defect

if TYPE_CHECKING:
    from datetime import datetime
    from xml.etree.ElementTree import Element  # nosec B405  # type only

    import pytest

    from podiumd_tests.environment import Environment

# Translate endpoints of the ZDS 1.2 messages; ZaakBrug picks the operation by the SOAPAction header.
ZDS = "/services/translate/generic/zds"
STUF = "http://www.egem.nl/StUF/StUF0301"
ZKN = "http://www.egem.nl/StUF/sector/zkn/0310"
XMLNS = f"xmlns:StUF={quoteattr(STUF)} xmlns:ZKN={quoteattr(ZKN)}"
# ZaakBrug's default organisation (zaakbrug.globals.organizations).
GEMEENTECODE = "1900"
# The mutation parameters shared by the Lk01 messages (creeerZaak, voegZaakdocumentToe).
MUTATIE = (
    "<ZKN:parameters><StUF:mutatiesoort>T</StUF:mutatiesoort>\n"
    "<StUF:indicatorOvername>V</StUF:indicatorOvername></ZKN:parameters>"
)


@dataclass(frozen=True)
class ZaakVelden:
    """Optional fields of a ZDS zaak object: a kenmerk (bron ptest) and a verlenging (duur, reden)."""

    kenmerk: str | None = None
    verlenging: tuple[int, str] | None = None

    def kenmerk_xml(self) -> str:
        """Return the kenmerk element; it comes before startdatum."""
        if self.kenmerk is None:
            return ""
        return f"<ZKN:kenmerk><ZKN:kenmerk>{self.kenmerk}</ZKN:kenmerk><ZKN:bron>ptest</ZKN:bron></ZKN:kenmerk>"

    def verlenging_xml(self) -> str:
        """Return the verlenging element; it comes after registratiedatum."""
        if self.verlenging is None:
            return ""
        duur, reden = self.verlenging
        return f"<ZKN:verlenging><ZKN:duur>{duur}</ZKN:duur><ZKN:reden>{reden}</ZKN:reden></ZKN:verlenging>"


NO_VELDEN = ZaakVelden()


class Document(NamedTuple):
    """A document for voegZaakdocumentToe: its identificatie, informatieobjecttype omschrijving, content and status."""

    identificatie: str
    documenttype: str
    inhoud_base64: str
    status: str = "In bewerking"


def soap_action(message: str) -> dict[str, str]:
    """Request headers of a ZDS message such as genereerZaakIdentificatie_Di02."""
    return {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f"{ZKN}/{message}"}


def _stuurgegevens(berichtcode: str, now: datetime, gemeentecode: str, *, rest: str) -> str:
    """Return the StUF stuurgegevens shared by the ZDS messages; rest adds elements after the standard ones.

    tijdstipBericht has 16 digits (hundredths of a second); more fails ZaakBrug's XML validation.
    """
    return f"""<ZKN:stuurgegevens><StUF:berichtcode>{berichtcode}</StUF:berichtcode>
<StUF:zender><StUF:organisatie>{gemeentecode}</StUF:organisatie>
<StUF:applicatie>ptest</StUF:applicatie></StUF:zender>
<StUF:ontvanger><StUF:organisatie>{gemeentecode}</StUF:organisatie>
<StUF:applicatie>CDR</StUF:applicatie></StUF:ontvanger>
<StUF:referentienummer>{uuid.uuid4()}</StUF:referentienummer>
<StUF:tijdstipBericht>{now:%Y%m%d%H%M%S}{now.microsecond // 10000:02d}</StUF:tijdstipBericht>
{rest}</ZKN:stuurgegevens>"""


def _isvan_zaaktype(code: str, verwerkingssoort: str) -> str:
    """Return the isVan reference to a zaaktype by its code, shared by creeerZaak and voegZaakdocumentToe."""
    return f"""<ZKN:isVan StUF:entiteittype="ZAKZKT" StUF:verwerkingssoort={quoteattr(verwerkingssoort)}>
<ZKN:gerelateerde StUF:entiteittype="ZKT" StUF:verwerkingssoort={quoteattr(verwerkingssoort)}>
<ZKN:omschrijving>podiumd-tests</ZKN:omschrijving><ZKN:code>{code}</ZKN:code>
<ZKN:ingangsdatumObject xsi:nil="true" StUF:noValue="geenWaarde"/></ZKN:gerelateerde></ZKN:isVan>"""


def genereer_zaak_id(now: datetime, gemeentecode: str = GEMEENTECODE) -> str:
    """Return a genereerZaakIdentificatie_Di02 envelope, for the VrijBericht endpoint."""
    stuurgegevens = _stuurgegevens(
        "Di02", now, gemeentecode, rest="<StUF:functie>genereerZaakidentificatie</StUF:functie>"
    )
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 {XMLNS}><SOAP-ENV:Body><ZKN:genereerZaakIdentificatie_Di02>
{stuurgegevens}</ZKN:genereerZaakIdentificatie_Di02></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def genereer_document_id(now: datetime, gemeentecode: str = GEMEENTECODE) -> str:
    """Return a genereerDocumentIdentificatie_Di02 envelope, for the VrijBericht endpoint."""
    stuurgegevens = _stuurgegevens(
        "Di02", now, gemeentecode, rest="<StUF:functie>genereerDocumentidentificatie</StUF:functie>"
    )
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 {XMLNS}><SOAP-ENV:Body><ZKN:genereerDocumentIdentificatie_Di02>
{stuurgegevens}</ZKN:genereerDocumentIdentificatie_Di02></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def document_identificatie(answer: str) -> str | None:
    """Return the document identificatie in a genereerDocumentIdentificatie answer, or None."""
    return _text(answer, f".//{{{ZKN}}}document/{{{ZKN}}}identificatie")


def creeer_zaak(  # noqa: PLR0913  # one message
    now: datetime,
    zaak: str,
    zaaktype_code: str,
    bsn: str,
    gemeentecode: str = GEMEENTECODE,
    *,
    velden: ZaakVelden = NO_VELDEN,
) -> str:
    """Return a creeerZaak_Lk01 envelope for the OntvangAsynchroon endpoint: a zaak of zaaktype_code with an initiator.

    zaaktype_code is the zaaktype identificatie and is at most 10 characters (the StUF code limit).
    """
    stuurgegevens = _stuurgegevens("Lk01", now, gemeentecode, rest="<StUF:entiteittype>ZAK</StUF:entiteittype>")
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:BG="http://www.egem.nl/StUF/sector/bg/0310" {XMLNS}
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><SOAP-ENV:Body><ZKN:zakLk01>
{stuurgegevens}
{MUTATIE}
<ZKN:object StUF:sleutelVerzendend={quoteattr(zaak)} StUF:entiteittype="ZAK" StUF:verwerkingssoort="T">
{_zaak_velden(now, zaak, velden)}
{_isvan_zaaktype(zaaktype_code, "T")}
<ZKN:heeftAlsInitiator StUF:entiteittype="ZAKBTRINI" StUF:verwerkingssoort="T"><ZKN:gerelateerde>
<ZKN:natuurlijkPersoon StUF:entiteittype="NPS" StUF:verwerkingssoort="T"><BG:inp.bsn>{bsn}</BG:inp.bsn>
<BG:geslachtsnaam>Ptest</BG:geslachtsnaam></ZKN:natuurlijkPersoon></ZKN:gerelateerde>
</ZKN:heeftAlsInitiator></ZKN:object></ZKN:zakLk01></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def _zaak_velden(now: datetime, zaak: str, velden: ZaakVelden) -> str:
    """Return the zaak object's own fields in StUF order: identificatie, omschrijving, kenmerk, dates, verlenging."""
    return f"""<ZKN:identificatie>{zaak}</ZKN:identificatie><ZKN:omschrijving>podiumd-tests ZaakBrug</ZKN:omschrijving>
{velden.kenmerk_xml()}<ZKN:startdatum>{now:%Y%m%d}</ZKN:startdatum>
<ZKN:registratiedatum>{now:%Y%m%d}</ZKN:registratiedatum>{velden.verlenging_xml()}"""


def _zaak_wijziging(
    now: datetime,
    zaak: str,
    zaaktype_code: str,
    changes: tuple[tuple[ZaakVelden, str], tuple[ZaakVelden, str]],
    gemeentecode: str,
) -> str:
    """Return a zakLk01 envelope (mutatiesoort W): the old zaak, then as it becomes, each with extra elements."""
    stuurgegevens = _stuurgegevens("Lk01", now, gemeentecode, rest="<StUF:entiteittype>ZAK</StUF:entiteittype>")
    objects = "".join(
        f"""<ZKN:object StUF:sleutelVerzendend={quoteattr(zaak)} StUF:entiteittype="ZAK" StUF:verwerkingssoort="W">
{_zaak_velden(now, zaak, velden)}
{_isvan_zaaktype(zaaktype_code, "I")}{extra}</ZKN:object>"""
        for velden, extra in changes
    )
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 {XMLNS} xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<SOAP-ENV:Body><ZKN:zakLk01>
{stuurgegevens}
<ZKN:parameters><StUF:mutatiesoort>W</StUF:mutatiesoort>
<StUF:indicatorOvername>V</StUF:indicatorOvername></ZKN:parameters>
{objects}</ZKN:zakLk01></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def update_zaak(  # noqa: PLR0913  # one message
    now: datetime,
    zaak: str,
    zaaktype_code: str,
    *,
    old: ZaakVelden,
    new: ZaakVelden,
    gemeentecode: str = GEMEENTECODE,
) -> str:
    """Return an updateZaak_Lk01 envelope for the OntvangAsynchroon endpoint: the old zaak, then as it becomes."""
    return _zaak_wijziging(now, zaak, zaaktype_code, ((old, ""), (new, "")), gemeentecode)


def actualiseer_zaakstatus(  # noqa: PLR0913  # one message
    now: datetime,
    zaak: str,
    zaaktype_code: str,
    *,
    volgnummer: int,
    omschrijving: str,
    gezet: datetime,
    gemeentecode: str = GEMEENTECODE,
) -> str:
    """Return an actualiseerZaakstatus_Lk01 envelope for the OntvangAsynchroon endpoint: give the zaak a new status."""
    zonder = (
        '<ZKN:heeft StUF:entiteittype="ZAKSTT" StUF:verwerkingssoort="T" xsi:nil="true" StUF:noValue="geenWaarde"/>'
    )
    status = f"""<ZKN:heeft StUF:entiteittype="ZAKSTT" StUF:verwerkingssoort="T">
<ZKN:gerelateerde StUF:entiteittype="STT" StUF:verwerkingssoort="I"><ZKN:zkt.code>{zaaktype_code}</ZKN:zkt.code>
<ZKN:zkt.omschrijving>podiumd-tests</ZKN:zkt.omschrijving><ZKN:volgnummer>{volgnummer:04d}</ZKN:volgnummer>
<ZKN:code>{volgnummer:04d}</ZKN:code><ZKN:omschrijving>{omschrijving}</ZKN:omschrijving>
<ZKN:ingangsdatumObject xsi:nil="true" StUF:noValue="geenWaarde"/></ZKN:gerelateerde>
<ZKN:datumStatusGezet>{gezet:%Y%m%d%H%M%S}00</ZKN:datumStatusGezet></ZKN:heeft>"""
    return _zaak_wijziging(now, zaak, zaaktype_code, ((NO_VELDEN, zonder), (NO_VELDEN, status)), gemeentecode)


def geef_zaak_details(now: datetime, zaak: str, gemeentecode: str = GEMEENTECODE) -> str:
    """Return a geefZaakdetails_Lv01 envelope for the BeantwoordVraag endpoint: read one zaak by identificatie."""
    stuurgegevens = _stuurgegevens("Lv01", now, gemeentecode, rest="<StUF:entiteittype>ZAK</StUF:entiteittype>")
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 {XMLNS} xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<SOAP-ENV:Body><ZKN:zakLv01>
{stuurgegevens}
<ZKN:parameters><StUF:sortering>0</StUF:sortering>
<StUF:indicatorVervolgvraag>false</StUF:indicatorVervolgvraag></ZKN:parameters>
<ZKN:gelijk StUF:entiteittype="ZAK"><ZKN:identificatie>{zaak}</ZKN:identificatie></ZKN:gelijk>
<ZKN:scope><ZKN:object StUF:entiteittype="ZAK"><ZKN:identificatie xsi:nil="true"/>
<ZKN:omschrijving xsi:nil="true"/>
<ZKN:isVan StUF:entiteittype="ZAKZKT"><ZKN:gerelateerde StUF:entiteittype="ZKT">
<ZKN:code xsi:nil="true"/></ZKN:gerelateerde></ZKN:isVan></ZKN:object></ZKN:scope>
</ZKN:zakLv01></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def voeg_zaakdocument_toe(
    now: datetime, zaak: str, zaaktype_code: str, document: Document, gemeentecode: str = GEMEENTECODE
) -> str:
    """Return a voegZaakdocumentToe_Lk01 envelope: attach one document to a zaak."""
    stuurgegevens = _stuurgegevens("Lk01", now, gemeentecode, rest="<StUF:entiteittype>EDC</StUF:entiteittype>")
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 {XMLNS} xmlns:xmime="http://www.w3.org/2005/05/xmlmime"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><SOAP-ENV:Body><ZKN:edcLk01>
{stuurgegevens}
{MUTATIE}
<ZKN:object StUF:entiteittype="EDC" StUF:verwerkingssoort="T">
<ZKN:identificatie>{document.identificatie}</ZKN:identificatie>
<ZKN:dct.omschrijving>{document.documenttype}</ZKN:dct.omschrijving>
<ZKN:creatiedatum>{now:%Y%m%d}</ZKN:creatiedatum><ZKN:titel>podiumd-tests document</ZKN:titel>
<ZKN:formaat>pdf</ZKN:formaat><ZKN:taal>nld</ZKN:taal>
<ZKN:versie xsi:nil="true" StUF:noValue="geenWaarde"/><ZKN:status>{document.status}</ZKN:status>
<ZKN:vertrouwelijkAanduiding>OPENBAAR</ZKN:vertrouwelijkAanduiding><ZKN:auteur>ptest</ZKN:auteur>
<ZKN:inhoud xmime:contentType="application/pdf" StUF:bestandsnaam="ptest.pdf">{document.inhoud_base64}</ZKN:inhoud>
<ZKN:isRelevantVoor StUF:entiteittype="EDCZAK" StUF:verwerkingssoort="T">
<ZKN:gerelateerde StUF:entiteittype="ZAK" StUF:verwerkingssoort="I">
<ZKN:identificatie>{zaak}</ZKN:identificatie><ZKN:omschrijving>podiumd-tests</ZKN:omschrijving>
{_isvan_zaaktype(zaaktype_code, "I")}
</ZKN:gerelateerde></ZKN:isRelevantVoor></ZKN:object></ZKN:edcLk01></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def _vrij_bericht(message: str, functie: str, now: datetime, gemeentecode: str, body: str) -> str:
    """Return a vrij bericht (Di02) envelope for the VrijBericht endpoint, with this body after its stuurgegevens."""
    stuurgegevens = _stuurgegevens("Di02", now, gemeentecode, rest=f"<StUF:functie>{functie}</StUF:functie>")
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 {XMLNS} xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<SOAP-ENV:Body><ZKN:{message}>
{stuurgegevens}
{body}</ZKN:{message}></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def geef_zaakdocument_bewerken(now: datetime, document: str, gemeentecode: str = GEMEENTECODE) -> str:
    """Return a geefZaakdocumentbewerken_Di02 envelope: check the document out for editing (answer: checkedOutId)."""
    body = f"""<ZKN:edcLv01 StUF:entiteittype="EDC" StUF:functie="selectie">
<ZKN:parameters><StUF:indicatorAfnemerIndicatie>false</StUF:indicatorAfnemerIndicatie></ZKN:parameters>
<ZKN:gelijk StUF:entiteittype="EDC"><ZKN:identificatie>{document}</ZKN:identificatie></ZKN:gelijk></ZKN:edcLv01>"""
    return _vrij_bericht("geefZaakdocumentbewerken_Di02", "geefZaakdocumentbewerken", now, gemeentecode, body)


def update_zaakdocument(  # noqa: PLR0913  # one message
    now: datetime, zaak: str, document: str, checkout: str, *, titel: str, gemeentecode: str = GEMEENTECODE
) -> str:
    """Return an updateZaakdocument_Di02 envelope: give the checked-out document a new titel."""
    body = f"""<ZKN:parameters><ZKN:checkedOutId>{checkout}</ZKN:checkedOutId></ZKN:parameters>
<ZKN:edcLk02 StUF:entiteittype="EDC" StUF:functie="update"><ZKN:parameters><StUF:mutatiesoort>W</StUF:mutatiesoort>
</ZKN:parameters><ZKN:object StUF:entiteittype="EDC" StUF:verwerkingssoort="W">
<ZKN:identificatie>{document}</ZKN:identificatie><ZKN:creatiedatum>{now:%Y%m%d}</ZKN:creatiedatum>
<ZKN:titel>{titel}</ZKN:titel><ZKN:formaat>pdf</ZKN:formaat><ZKN:taal>nld</ZKN:taal>
<ZKN:versie xsi:nil="true" StUF:noValue="waardeOnbekend"/><ZKN:status>In bewerking</ZKN:status>
<ZKN:vertrouwelijkAanduiding>OPENBAAR</ZKN:vertrouwelijkAanduiding><ZKN:auteur>ptest</ZKN:auteur>
<ZKN:isRelevantVoor StUF:entiteittype="EDCZAK" StUF:verwerkingssoort="T">
<ZKN:gerelateerde StUF:entiteittype="ZAK" StUF:verwerkingssoort="T"><ZKN:identificatie>{zaak}</ZKN:identificatie>
</ZKN:gerelateerde></ZKN:isRelevantVoor></ZKN:object></ZKN:edcLk02>"""
    return _vrij_bericht("updateZaakdocument_Di02", "updateZaakdocument", now, gemeentecode, body)


def cancel_checkout(now: datetime, document: str, checkout: str, gemeentecode: str = GEMEENTECODE) -> str:
    """Return a cancelCheckout_Di02 envelope: release a checked-out document."""
    body = f"""<ZKN:parameters><ZKN:checkedOutId>{checkout}</ZKN:checkedOutId></ZKN:parameters>
<ZKN:document StUF:entiteittype="EDC" StUF:verwerkingssoort="W" StUF:functie="entiteit">
<ZKN:identificatie>{document}</ZKN:identificatie></ZKN:document>"""
    return _vrij_bericht("cancelCheckout_Di02", "cancelCheckout", now, gemeentecode, body)


def checked_out_id(answer: str) -> str | None:
    """Return the checkedOutId in a geefZaakdocumentbewerken answer, or None."""
    return _text(answer, f".//{{{ZKN}}}checkedOutId")


def is_fault(answer: str) -> bool:
    """Return True when the ZDS answer is a SOAP Fault (ZaakBrug answers its Fo03 faults with HTTP 200)."""
    return _parsed(answer).find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault") is not None


def zaak_identificatie(answer: str) -> str | None:
    """Return the zaak identificatie in a ZDS answer, or None.

    genereerZaakIdentificatie answers it under zaak/identificatie; geefZaakdetails (La01) under object/identificatie.
    """
    root = _parsed(answer)
    for path in (f".//{{{ZKN}}}zaak/{{{ZKN}}}identificatie", f".//{{{ZKN}}}object/{{{ZKN}}}identificatie"):
        found = root.find(path)
        if found is not None and found.text:
            return found.text
    return None


def is_bevestiging(answer: str) -> bool:
    """Return True when the ZDS answer is a Bv03 confirmation (not an Fo03 fault)."""
    return _text(answer, f".//{{{STUF}}}berichtcode") == "Bv03"


def _parsed(answer: str) -> Element:
    return fromstring(answer)  # noqa: S314  # nosec B314  # ZaakBrug's own answer


def _text(answer: str, path: str) -> str | None:
    """Return the text of the answer's first element at path, or None."""
    found = _parsed(answer).find(path)
    return None if found is None else found.text


# ZaakBrug takes the statustype from a zaak's own zaaktype version from this release on (zaakbrug-3).
EXPIRED_VERSION_FIXED = (1, 27, 0)


def expect_expired_version_bug(request: pytest.FixtureRequest, env: Environment) -> None:
    """Mark the test a strict xfail when the deployed ZaakBrug is older than 1.27.0."""
    expect_defect(
        request,
        env,
        "zaakbrug",
        lambda version: version < EXPIRED_VERSION_FIXED,
        raises=AssertionError,
        reason="[zaakbrug-3] ZaakBrug before 1.27.0 takes the statustype from the zaaktype version valid today:"
        " a status on a zaak of an expired version fails ('Adding a new status is failed'); fixed in 1.27.0",
    )
