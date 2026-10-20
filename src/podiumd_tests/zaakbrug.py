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


def genereer_zaak_identificatie(now: datetime, gemeentecode: str = GEMEENTECODE) -> str:
    """A genereerZaakIdentificatie_Di02 envelope, for the VrijBericht endpoint.

    StUF's tijdstipBericht has hundredths of a second: 16 digits; more fails ZaakBrug's XML validation.
    """
    return f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:StUF="{STUF}" xmlns:ZKN="{ZKN}"><SOAP-ENV:Body><ZKN:genereerZaakIdentificatie_Di02>
<ZKN:stuurgegevens><StUF:berichtcode>Di02</StUF:berichtcode>
<StUF:zender><StUF:organisatie>{gemeentecode}</StUF:organisatie>
<StUF:applicatie>ptest</StUF:applicatie></StUF:zender>
<StUF:ontvanger><StUF:organisatie>{gemeentecode}</StUF:organisatie>
<StUF:applicatie>CDR</StUF:applicatie></StUF:ontvanger>
<StUF:referentienummer>{uuid.uuid4()}</StUF:referentienummer>
<StUF:tijdstipBericht>{now:%Y%m%d%H%M%S}{now.microsecond // 10000:02d}</StUF:tijdstipBericht>
<StUF:functie>genereerZaakidentificatie</StUF:functie></ZKN:stuurgegevens>
</ZKN:genereerZaakIdentificatie_Di02></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


def zaak_identificatie(answer: str) -> str | None:
    """The zaak identificatie in a ZDS answer, or None."""
    found = ET.fromstring(answer).find(f".//{{{ZKN}}}zaak/{{{ZKN}}}identificatie")  # noqa: S314  # nosec B314
    return found.text if found is not None else None
