"""ZaakBrug: ZDS 1.2 (StUF-ZKN 3.10) SOAP calls that it translates to the ZGW APIs."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET  # nosec B405  # parses ZaakBrug's own answer

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

# Translate endpoints of the ZDS 1.2 messages; ZaakBrug picks the operation by the SOAPAction header.
ZDS = "/services/translate/generic/zds"
STUF = "http://www.egem.nl/StUF/StUF0301"
ZKN = "http://www.egem.nl/StUF/sector/zkn/0310"
# ZaakBrug's default organisation (zaakbrug.globals.organizations).
GEMEENTECODE = "1900"


def soap_action(message: str) -> dict[str, str]:
    """Request headers of a ZDS message such as genereerZaakIdentificatie_Di02."""
    return {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f"{ZKN}/{message}"}


def _stuurgegevens(berichtcode: str, now: datetime, gemeentecode: str, *, rest: str) -> str:
    """The StUF stuurgegevens shared by the ZDS messages; rest adds elements after the standard ones.

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


def genereer_zaak_identificatie(now: datetime, gemeentecode: str = GEMEENTECODE) -> str:
    """A genereerZaakIdentificatie_Di02 envelope, for the VrijBericht endpoint."""
    stuurgegevens = _stuurgegevens(
        "Di02", now, gemeentecode, rest="<StUF:functie>genereerZaakidentificatie</StUF:functie>"
    )
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:StUF="{STUF}" xmlns:ZKN="{ZKN}"><SOAP-ENV:Body><ZKN:genereerZaakIdentificatie_Di02>
{stuurgegevens}</ZKN:genereerZaakIdentificatie_Di02></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def creeer_zaak(now: datetime, zaak: str, zaaktype_code: str, bsn: str, gemeentecode: str = GEMEENTECODE) -> str:
    """A creeerZaak_Lk01 envelope for the OntvangAsynchroon endpoint: one zaak of zaaktype_code with an initiator.

    zaaktype_code is the zaaktype identificatie and is at most 10 characters (the StUF code limit).
    """
    stuurgegevens = _stuurgegevens("Lk01", now, gemeentecode, rest="<StUF:entiteittype>ZAK</StUF:entiteittype>")
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:BG="http://www.egem.nl/StUF/sector/bg/0310" xmlns:StUF="{STUF}" xmlns:ZKN="{ZKN}"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><SOAP-ENV:Body><ZKN:zakLk01>
{stuurgegevens}
<ZKN:parameters><StUF:mutatiesoort>T</StUF:mutatiesoort>
<StUF:indicatorOvername>V</StUF:indicatorOvername></ZKN:parameters>
<ZKN:object StUF:sleutelVerzendend="{zaak}" StUF:entiteittype="ZAK" StUF:verwerkingssoort="T">
<ZKN:identificatie>{zaak}</ZKN:identificatie><ZKN:omschrijving>podiumd-tests ZaakBrug</ZKN:omschrijving>
<ZKN:startdatum>{now:%Y%m%d}</ZKN:startdatum><ZKN:registratiedatum>{now:%Y%m%d}</ZKN:registratiedatum>
<ZKN:isVan StUF:entiteittype="ZAKZKT" StUF:verwerkingssoort="T">
<ZKN:gerelateerde StUF:entiteittype="ZKT" StUF:verwerkingssoort="T">
<ZKN:omschrijving>podiumd-tests</ZKN:omschrijving><ZKN:code>{zaaktype_code}</ZKN:code>
<ZKN:ingangsdatumObject xsi:nil="true" StUF:noValue="geenWaarde"/></ZKN:gerelateerde></ZKN:isVan>
<ZKN:heeftAlsInitiator StUF:entiteittype="ZAKBTRINI" StUF:verwerkingssoort="T"><ZKN:gerelateerde>
<ZKN:natuurlijkPersoon StUF:entiteittype="NPS" StUF:verwerkingssoort="T"><BG:inp.bsn>{bsn}</BG:inp.bsn>
<BG:geslachtsnaam>Ptest</BG:geslachtsnaam></ZKN:natuurlijkPersoon></ZKN:gerelateerde>
</ZKN:heeftAlsInitiator></ZKN:object></ZKN:zakLk01></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def geef_zaak_details(now: datetime, zaak: str, gemeentecode: str = GEMEENTECODE) -> str:
    """A geefZaakdetails_Lv01 envelope for the BeantwoordVraag endpoint: read one zaak by identificatie."""
    stuurgegevens = _stuurgegevens("Lv01", now, gemeentecode, rest="<StUF:entiteittype>ZAK</StUF:entiteittype>")
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:StUF="{STUF}" xmlns:ZKN="{ZKN}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
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


def zaak_identificatie(answer: str) -> str | None:
    """The zaak identificatie in a ZDS answer, or None.

    genereerZaakIdentificatie answers it under zaak/identificatie; geefZaakdetails (La01) under object/identificatie.
    """
    root = ET.fromstring(answer)  # noqa: S314  # nosec B314  # ZaakBrug's own answer
    for path in (f".//{{{ZKN}}}zaak/{{{ZKN}}}identificatie", f".//{{{ZKN}}}object/{{{ZKN}}}identificatie"):
        found = root.find(path)
        if found is not None and found.text:
            return found.text
    return None


def is_bevestiging(answer: str) -> bool:
    """True when the ZDS answer is a Bv03 confirmation (not an Fo03 fault)."""
    code = ET.fromstring(answer).find(f".//{{{STUF}}}berichtcode")  # noqa: S314  # nosec B314  # ZaakBrug's own answer
    return code is not None and code.text == "Bv03"
