"""Chain: ZAC mails an ontvangstbevestiging for a productaanvraag of the environment's own wiring.

The productaanvraagtype and zaaktype are those of profile settings productaanvraag_type and productaanvraag_zaaktype.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.mailpit import received_message
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.openklant import make_submission_contact
from podiumd_tests.zac import BEVESTIGING_NIET_VERSTUURD
from podiumd_tests.zac import PRODUCTAANVRAAG_TIMEOUT
from podiumd_tests.zac import mail_address
from podiumd_tests.zac import productaanvraag_zaak
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import read_zaakafhandelparameters
from podiumd_tests.zac_documents import zaak_documents

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.core,
    pytest.mark.requires("cluster", "objecten", "opennotificaties", "zac", "openzaak"),
]


@pytest.mark.tc("OF-002")
@pytest.mark.requires("openklant", "mailpit", "keycloak")
@pytest.mark.usefixtures("ontvangstbevestiging")
@pytest.mark.source(
    "draaiboek OF-002",
    "A form leads to a zaak in ZAC, which automatically sends a receipt confirmation with the zaaknummer.",
)
@pytest.mark.scenario("""
    Given a form's submitter left an e-mail address in Open Klant
    When the form's productaanvraag makes ZAC start a zaak
    Then the submitter receives a mail with the zaaknummer, from and with reply-to the zaaktype's afzenders
    And the zaak keeps the mail as a document and no longer has the indicatie that no bevestiging was sent
""")
def test_zac_mails_the_initiator_an_ontvangstbevestiging(
    podiumd_env: Environment,
    zac: requests.Session,
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    productaanvraag_objecttype: str,
) -> None:
    """ZAC mails the zaaknummer to the address the submitter left, per the ZAPs' automaticEmailConfirmation."""
    kenmerk = registry.tagged("bevestigd")
    adres = f"{kenmerk}@example.invalid"
    make_submission_contact(openklant, registry, kenmerk, adres)
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, productaanvraagtype, kenmerk)
    zaak = productaanvraag_zaak(openzaak_productaanvraag, registry, kenmerk)
    message = received_message(mailpit, registry, timeout=PRODUCTAANVRAAG_TIMEOUT, to=adres)
    assert str(zaak["identificatie"]) in str(message.get("HTML"))
    zac_url = podiumd_env.profile.urls["zac"]
    parameters = read_zaakafhandelparameters(zac, zac_url, uuid_of(zaak["zaaktype"]))
    bevestiging = section(parameters, "automaticEmailConfirmation")
    afzender = mail_address(podiumd_env, str(bevestiging["emailSender"]))
    assert section(message, "From").get("Address") == afzender
    reply_to = [found.get("Address") for found in entries(message.get("ReplyTo"))]
    # ZAC leaves out a reply-to that equals the afzender.
    antwoord = mail_address(podiumd_env, str(bevestiging["emailReply"]))
    assert reply_to == [adres for adres in (antwoord,) if adres != afzender]
    titels = {str(document.get("titel")) for document in zaak_documents(zac, zac_url, zaak)}
    assert message["Subject"] in titels
    shown = read_zaak(zac, zac_url, str(zaak["uuid"]))
    assert BEVESTIGING_NIET_VERSTUURD not in strings(shown.get("indicaties"))
