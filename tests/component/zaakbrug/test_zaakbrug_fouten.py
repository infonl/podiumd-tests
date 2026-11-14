"""ZaakBrug's answers to messages it cannot handle: a wrong SOAPAction, invalid XML and an unknown path."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.zaakbrug import ZDS
from podiumd_tests.zaakbrug import berichtcode
from podiumd_tests.zaakbrug import genereer_zaak_id
from podiumd_tests.zaakbrug import is_fault
from podiumd_tests.zaakbrug import soap_action

if TYPE_CHECKING:
    import requests

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zaakbrug"),
    pytest.mark.source(
        "upstream Sudwest-Fryslan/OpenZaakBrug src/test/resources/ladybug/ErrorHandling",
        "A message the bridge cannot handle gets a SOAP Fault, not a server error page or a hang.",
    ),
]

GENEREER = "genereerZaakIdentificatie_Di02"


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({**soap_action(GENEREER), "SOAPAction": "UnknownSoapAction"}, id="unknown-soapaction"),
        pytest.param(soap_action("genereerDocumentIdentificatie_Di02"), id="soapaction-of-another-message"),
    ],
)
@pytest.mark.scenario("""
    Given ZaakBrug answers ZDS 1.2 messages
    When a client sends a genereerZaakIdentificatie message with an unknown SOAPAction or that of another message
    Then ZaakBrug answers with a SOAP Fault that carries a StUF Fo03 bericht
""")
def test_wrong_soapaction_gets_a_fo03_fault(
    http: requests.Session, urls: dict[str, str], headers: dict[str, str]
) -> None:
    """A SOAPAction that does not name the message's operation gets a SOAP Fault with a Fo03."""
    envelope = genereer_zaak_id(datetime.now(UTC))
    answer = http.post(f"{urls['zaakbrug']}{ZDS}/VrijBericht", data=envelope, headers=headers).text
    assert (is_fault(answer), berichtcode(answer)) == (True, "Fo03")


@pytest.mark.parametrize(
    ("path", "cut"),
    [pytest.param("VrijBericht", 40, id="invalid-xml"), pytest.param("InvalidPath", 0, id="unknown-path")],
)
@pytest.mark.scenario("""
    Given ZaakBrug answers ZDS 1.2 messages
    When a client sends a genereerZaakIdentificatie message that is cut off, or to a path ZaakBrug does not serve
    Then ZaakBrug answers with a SOAP Fault
""")
def test_invalid_xml_and_unknown_path_get_a_soap_fault(
    http: requests.Session, urls: dict[str, str], path: str, cut: int
) -> None:
    """A message that is no XML, or one to an unknown translate path, gets a SOAP Fault."""
    envelope = genereer_zaak_id(datetime.now(UTC))
    body = envelope[: len(envelope) - cut]
    answer = http.post(f"{urls['zaakbrug']}{ZDS}/{path}", data=body, headers=soap_action(GENEREER)).text
    assert is_fault(answer)
