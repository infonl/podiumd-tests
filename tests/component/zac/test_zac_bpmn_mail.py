"""A BPMN process that mails: SendEmailDelegate after the intake, SendConfirmationEmailDelegate from task Keuze."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import INTAKE
from podiumd_tests.bootstrap.bpmn import KEUZE
from podiumd_tests.bootstrap.bpmn import MAIL_TO
from podiumd_tests.bootstrap.bpmn import MAIL_VERTROUWELIJKHEID
from podiumd_tests.bootstrap.bpmn import SELECT
from podiumd_tests.bootstrap.bpmn import complete_intake
from podiumd_tests.bootstrap.bpmn import complete_keuze
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.mailpit import own_address
from podiumd_tests.mailpit import received_message
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.seed.openklant import ZAC_ZAAK
from podiumd_tests.seed.openklant import make_submission_contact
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import zaaktype_parts
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import NOTIFICATION_TIMEOUT
from podiumd_tests.zac_documents import OPENBAAR_MAIL
from podiumd_tests.zac_documents import inbox_document
from podiumd_tests.zac_documents import inbox_documenten
from podiumd_tests.zac_documents import kept_mail
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_documents import zaak_documents
from podiumd_tests.zac_taken import is_task_open
from podiumd_tests.zac_taken import open_task

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "pabc", "keycloak", "mailpit"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, bpmn): BPMN mail"
        " and the form field ZAC_vertrouwelijkheidaanduiding.",
    ),
]

MAIL_TIMEOUT = 60
# The subject of ZAC's mail template Algemene e-mail, which the process sends.
SUBJECT = "Informatie over zaak {}"


@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC whose process mails after the intake
    When the behandelaar submits the intake with an e-mail address and the vertrouwelijkheid zaakvertrouwelijk
    Then the mail with the zaak's number in its subject arrives at the address
    And the zaak has the mail as a PDF, zaakvertrouwelijk
""")
def test_bpmn_mail_is_sent_and_stored_with_its_vertrouwelijkheid(
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """SendEmailDelegate fills the template's {ZAAK_NUMMER} and stores the mail with the form's vertrouwelijkheid."""
    zac_url = urls["zac"]
    adres = own_address(registry)
    form = {MAIL_TO: adres, MAIL_VERTROUWELIJKHEID: "ZAAKVERTROUWELIJK"}
    complete_intake(zac, zac_url, bpmn_zaak, (zac_group, ADMIN.username), **form)
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=adres)
    subject = SUBJECT.format(bpmn_zaak["identificatie"])
    assert message.get("Subject") == subject
    stored = [document for document in zaak_documents(zac, zac_url, bpmn_zaak) if document.get("titel") == subject]
    assert [str(document.get("vertrouwelijkheidaanduiding")).upper() for document in stored] == ["ZAAKVERTROUWELIJK"]


@pytest.mark.parametrize("vertrouwelijkheid", ["ONBEKEND", None], ids=["invalid", "missing"])
@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC whose process mails after the intake
    When the behandelaar submits the intake with an e-mail address but an unknown or no vertrouwelijkheid
    Then ZAC refuses the intake, and it stays open
""")
def test_bpmn_mail_without_a_valid_vertrouwelijkheid_fails_the_taak(
    zac: requests.Session,
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    registry: ResourceRegistry,
    vertrouwelijkheid: str | None,
) -> None:
    """SendEmailDelegate refuses a missing or unknown vertrouwelijkheidaanduiding, so the intake is not completed."""
    zac_url = urls["zac"]
    form = {MAIL_TO: own_address(registry)}
    if vertrouwelijkheid:
        form[MAIL_VERTROUWELIJKHEID] = vertrouwelijkheid
    taak = open_task(zac, zac_url, str(bpmn_zaak["uuid"]), INTAKE)
    with pytest.raises(UnexpectedStatusError):
        complete_intake(zac, zac_url, bpmn_zaak, (zac_group, ADMIN.username), **form)
    assert is_task_open(zac, zac_url, str(taak["id"]))


@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, documenten-mail):"
    " documents linked to a zaak in the BPMN flow do not land in Inbox documenten.",
)
@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC whose process mails after the intake
    When the behandelaar submits the intake, so the zaak keeps the mail as a PDF
    And uploads a document to the zaak and one to its open taak
    And a document on no zaak reaches the Inbox documenten after them
    Then the Inbox documenten list none of the zaak's three documents
""")
def test_bpmn_zaak_documents_are_not_in_inbox_documenten(
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    bpmn_zaaktype: JsonObject,
    bpmn_zaak: JsonObject,
    zac_group: str,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """ZAC drops a new document from its Inbox documenten once Open Zaak notifies its zaakinformatieobject.

    The document on no zaak shows that ZAC has handled the notifications of the documents before it.
    """
    zac_url = urls["zac"]
    adres = own_address(registry)
    complete_intake(
        zac, zac_url, bpmn_zaak, (zac_group, ADMIN.username), **{MAIL_TO: adres, MAIL_VERTROUWELIJKHEID: "OPENBAAR"}
    )
    subject = str(received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=adres).get("Subject"))
    taak = open_task(zac, zac_url, str(bpmn_zaak["uuid"]), SELECT)
    uploaded = [uploaded_document(zac, zac_url, bpmn_zaak, registry, taak=found) for found in (None, taak)]
    later = make_document(openzaak, registry, zaaktype_parts(openzaak, bpmn_zaaktype).informatieobjecttype)
    wait_until(
        lambda: inbox_document(zac, zac_url, later),
        timeout=NOTIFICATION_TIMEOUT,
        description=f"{later['url']} in ZAC's Inbox documenten",
    )
    documents = {str(document["uuid"]) for document in zaak_documents(zac, zac_url, bpmn_zaak)}
    assert {str(document["uuid"]) for document in uploaded} < documents
    assert len(documents) == len(uploaded) + 1, documents  # and the mail
    listed = inbox_documenten(zac, zac_url, registry.run_tag) + inbox_documenten(zac, zac_url, subject)
    assert not documents & {str(entry.get("enkelvoudiginformatieobjectUUID")) for entry in listed}


@pytest.mark.requires("openklant")
@pytest.mark.source(
    "external Dimpact-Samenwerking/zaakafhandelcomponent-configuratie end-to-end-testproces (E2E)",
    "Automatisch verzenden ontvangstbevestiging, reimplemented on podiumd-tests' process (the source has no licence).",
)
@pytest.mark.scenario("""
    Given a BPMN zaak in ZAC at its Keuze taak, without contactgegevens in Open Klant
    When the behandelaar chooses the ontvangstbevestiging
    Then no mail is sent, and the process goes on to a new Keuze taak
    When Open Klant gets a klantcontact about the zaak whose klant left an e-mail address
    And the behandelaar chooses the ontvangstbevestiging again
    Then the ontvangstbevestiging with the zaak's number arrives at that address
    And the zaak keeps the mail as a definitive PDF/A, openbaar
""")
def test_bpmn_ontvangstbevestiging_goes_to_the_zaaks_contactgegevens(
    zac: requests.Session,
    urls: dict[str, str],
    keuze_zaak: JsonObject,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """SendConfirmationEmailDelegate mails the zaak-specific contactgegevens in Open Klant, else skips the mail."""
    zac_url, uuid = urls["zac"], str(keuze_zaak["uuid"])
    complete_keuze(zac, zac_url, keuze_zaak, "bevestiging")
    open_task(zac, zac_url, uuid, KEUZE)
    assert zaak_documents(zac, zac_url, keuze_zaak) == []
    adres = own_address(registry)
    make_submission_contact(openklant, registry, uuid, adres, codes=ZAC_ZAAK)
    complete_keuze(zac, zac_url, keuze_zaak, "bevestiging")
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=adres)
    assert str(keuze_zaak["identificatie"]) in str(message.get("Subject")), message.get("Subject")
    assert kept_mail(zac, zac_url, keuze_zaak, message) == OPENBAAR_MAIL
