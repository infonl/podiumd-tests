"""ZAC: mail from a zaak (E-mail versturen, Bevestiging versturen), as ZAC's REST API sends it for the UI.

The mails go to run-tagged addresses at Mailpit; cleanup deletes them.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.mailpit import own_address
from podiumd_tests.mailpit import received_message
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import afzenders
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import send_mail
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
    pytest.mark.requires("zac", "openzaak", "mailpit"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, documenten-mail).",
    ),
]

MAIL_TIMEOUT = 60
REPLY_TO = "antwoord@example.com"
NIET_VERSTUURD = "ONTVANGSTBEVESTIGING_NIET_VERSTUURD"


@pytest.fixture(name="mail")
def fixture_mail(zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry) -> Callable[..., JsonObject]:
    """Return a mail from the zaak to a run-tagged address, from ZAC's first afzender; fields override."""

    def build(zaak: JsonObject, **fields: object) -> JsonObject:
        return {
            "verzender": afzenders(zac, urls["zac"], zaak)[0]["mail"],
            "ontvanger": own_address(registry),
            "onderwerp": "Zaak {ZAAK_NUMMER}",
            "body": "<p>Over zaak {ZAAK_NUMMER}: {ZAAK_OMSCHRIJVING}</p>",
            "createDocumentFromMail": False,
            "vertrouwelijkheidaanduiding": "OPENBAAR",
            **fields,
        }

    return build


def _titles(zac: requests.Session, zac_url: str, zaak: JsonObject) -> dict[str, object]:
    """The zaak's documents in ZAC: titel -> vertrouwelijkheidaanduiding."""
    return {
        str(item.get("titel")): item.get("vertrouwelijkheidaanduiding") for item in zaak_documents(zac, zac_url, zaak)
    }


@pytest.mark.scenario("""
    Given a zaak in ZAC with a document
    When the behandelaar mails it with the document attached and a reply-to address
    And keeps the mail as a vertrouwelijk document
    Then the mail arrives from ZAC's afzender with the reply-to address and the attachment
    And the zaaknummer and omschrijving in its subject and text are filled in
    And the zaak has the mail as a PDF, vertrouwelijk
""")
def test_email_with_an_attachment_arrives_and_is_kept_on_the_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    mail: Callable[..., JsonObject],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """E-mail versturen with bijlagen, replyTo and createDocumentFromMail; variables resolved; PDF stored."""
    zaak = zac_zaak()
    document = uploaded_document(zac, urls["zac"], zaak, registry)
    body = mail(
        zaak,
        replyTo=REPLY_TO,
        bijlagen=document["uuid"],
        createDocumentFromMail=True,
        vertrouwelijkheidaanduiding="VERTROUWELIJK",
    )
    expect_status(send_mail(zac, urls["zac"], zaak, body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=str(body["ontvanger"]))
    subject = f"Zaak {zaak['identificatie']}"
    assert message.get("Subject") == subject
    assert f"Over zaak {zaak['identificatie']}: {zaak['omschrijving']}" in str(message.get("HTML"))
    assert section(message, "From").get("Address") == body["verzender"]
    assert [item.get("Address") for item in entries(message.get("ReplyTo"))] == [REPLY_TO]
    assert [item.get("FileName") for item in entries(message.get("Attachments"))] == [document["bestandsnaam"]]
    assert _titles(zac, urls["zac"], zaak).get(subject) == "VERTROUWELIJK"


@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar mails it without keeping the mail as a document
    Then the mail arrives
    And the zaak has no new document
""")
def test_email_without_keeping_it_adds_no_document(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    mail: Callable[..., JsonObject],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """E-mail versturen without createDocumentFromMail leaves the zaak's documents as they were."""
    zaak = zac_zaak()
    before = _titles(zac, urls["zac"], zaak)
    body = mail(zaak)
    expect_status(send_mail(zac, urls["zac"], zaak, body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=str(body["ontvanger"]))
    assert _titles(zac, urls["zac"], zaak) == before


@pytest.mark.scenario("""
    Given a new zaak in ZAC, which shows that no ontvangstbevestiging was sent
    When the behandelaar sends the ontvangstbevestiging and keeps it as a document
    Then the mail arrives, the zaak has it as a document, and the indication is gone
    And a second ontvangstbevestiging is refused
""")
def test_ontvangstbevestiging_is_sent_once_and_clears_the_indicatie(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    mail: Callable[..., JsonObject],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """Bevestiging versturen clears ONTVANGSTBEVESTIGING_NIET_VERSTUURD, stores the mail, and works once."""
    zaak = zac_zaak()
    assert NIET_VERSTUURD in strings(read_zaak(zac, urls["zac"], str(zaak["uuid"])).get("indicaties"))
    body = mail(zaak, onderwerp="Ontvangstbevestiging {ZAAK_NUMMER}", createDocumentFromMail=True)
    expect_status(send_mail(zac, urls["zac"], zaak, body, acknowledge=True), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=str(body["ontvanger"]))
    assert _titles(zac, urls["zac"], zaak).get(f"Ontvangstbevestiging {zaak['identificatie']}") == "OPENBAAR"
    assert NIET_VERSTUURD not in strings(read_zaak(zac, urls["zac"], str(zaak["uuid"])).get("indicaties"))
    expect_status(send_mail(zac, urls["zac"], zaak, body, acknowledge=True), *REFUSED)


@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar sends a mail without choosing a vertrouwelijkheidaanduiding
    Then ZAC refuses it
""")
def test_email_needs_a_vertrouwelijkheidaanduiding(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], mail: Callable[..., JsonObject]
) -> None:
    """E-mail versturen without vertrouwelijkheidaanduiding answers 400."""
    zaak = zac_zaak()
    body = mail(zaak, vertrouwelijkheidaanduiding=None)
    expect_status(send_mail(zac, urls["zac"], zaak, body), HTTPStatus.BAD_REQUEST)
