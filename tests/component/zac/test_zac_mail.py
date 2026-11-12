"""ZAC: mail from a zaak (E-mail versturen, Bevestiging versturen, afhandelen, intake afronden) as ZAC's UI sends it.

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
from podiumd_tests.pdf import pdfa_problems
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import afzenders
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import send_mail
from podiumd_tests.zac import user_event
from podiumd_tests.zac import zaak_historie
from podiumd_tests.zac import zaak_mailtemplate
from podiumd_tests.zac_documents import document_url
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
REPLY_TO = "antwoord@example.invalid"
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


def _attachments(message: JsonObject) -> list[object]:
    """The file names of the Mailpit message's attachments."""
    return [item.get("FileName") for item in entries(message.get("Attachments"))]


@pytest.mark.scenario("""
    Given a zaak in ZAC with a document
    When the behandelaar mails it with the document attached and a reply-to address
    And keeps the mail as a vertrouwelijk document
    Then the mail arrives from ZAC's afzender with the reply-to address and the attachment
    And the zaaknummer and omschrijving in its subject and text are filled in
    And the zaak has the mail as a vertrouwelijk PDF/A-2b and PDF/UA with embedded fonts
""")
def test_email_with_an_attachment_arrives_and_is_kept_on_the_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    mail: Callable[..., JsonObject],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """E-mail versturen with bijlagen, replyTo and createDocumentFromMail; variables resolved; PDF/A stored."""
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
    assert _attachments(message) == [document["bestandsnaam"]]
    assert _titles(zac, urls["zac"], zaak).get(subject) == "VERTROUWELIJK"
    stored = next(item for item in zaak_documents(zac, urls["zac"], zaak) if item.get("titel") == subject)
    pdf = expect_status(zac.get(f"{document_url(urls['zac'], stored)}/download"), HTTPStatus.OK).content
    assert pdfa_problems(pdf) == []


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
    Given a new zaak in ZAC with a document, which shows that no ontvangstbevestiging was sent
    When the behandelaar sends the ontvangstbevestiging with the document attached
    Then the mail arrives with the attachment, and the indication is gone
    And the zaak has the mail as a document, and its historie shows it
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
    """Bevestiging versturen with bijlagen clears ONTVANGSTBEVESTIGING_NIET_VERSTUURD, stores the mail, and works once.

    ZAC's dialog always stores the mail; its historie line is the GEKOPPELD zaakinformatieobject of that document.
    """
    zaak = zac_zaak()
    assert NIET_VERSTUURD in strings(read_zaak(zac, urls["zac"], str(zaak["uuid"])).get("indicaties"))
    document = uploaded_document(zac, urls["zac"], zaak, registry)
    body = mail(
        zaak, onderwerp="Ontvangstbevestiging {ZAAK_NUMMER}", bijlagen=document["uuid"], createDocumentFromMail=True
    )
    expect_status(send_mail(zac, urls["zac"], zaak, body, acknowledge=True), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=str(body["ontvanger"]))
    assert _attachments(message) == [document["bestandsnaam"]]
    subject = f"Ontvangstbevestiging {zaak['identificatie']}"
    assert _titles(zac, urls["zac"], zaak).get(subject) == "OPENBAAR"
    historie = [(line.get("actie"), line.get("nieuweWaarde")) for line in zaak_historie(zac, urls["zac"], zaak)]
    assert ("GEKOPPELD", subject) in historie
    assert NIET_VERSTUURD not in strings(read_zaak(zac, urls["zac"], str(zaak["uuid"])).get("indicaties"))
    expect_status(send_mail(zac, urls["zac"], zaak, body, acknowledge=True), *REFUSED)


@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC
    When the behandelaar afhandelt it with a resultaat and the afhandelmail of its mailtemplate
    Then the zaak is closed
    And the afhandelmail arrives with the zaak's variables filled in
    And the zaak has the mail as a document
""")
def test_afhandelmail_arrives_and_is_kept_on_the_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    mail: Callable[..., JsonObject],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """ZAAK_AFHANDELEN with restMailGegevens of mailtemplate ZAAK_AFGEHANDELD, as ZAC's afhandelen dialog sends it."""
    zaak = zac_zaak()
    template = zaak_mailtemplate(zac, urls["zac"], zaak, "ZAAK_AFGEHANDELD")
    if template is None:
        pytest.skip("ZAC has no mailtemplate ZAAK_AFGEHANDELD: add one in ZAC's beheer of mailtemplates")
    afronden_intake(zac, urls["zac"], zaak)
    body = mail(zaak, onderwerp=template["onderwerp"], body=template["body"], createDocumentFromMail=True)
    expect_status(afhandelen(zac, urls["zac"], zaak, restMailGegevens=body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is False
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=str(body["ontvanger"]))
    assert "{" not in f"{message.get('Subject')}{message.get('HTML')}"
    assert message.get("Subject") in _titles(zac, urls["zac"], zaak)


def _intake_mail(  # the zaak, its mail and Mailpit
    zac: requests.Session,
    zac_url: str,
    zaak: JsonObject,
    mail: Callable[..., JsonObject],
    mailpit: ApiClient,
    registry: ResourceRegistry,
    mailtemplate: str,
    *,
    ontvankelijk: bool,
) -> JsonObject:
    """Finish the intake with the mail of the mailtemplate, as ZAC's intake afronden dialog sends it; the mail."""
    template = zaak_mailtemplate(zac, zac_url, zaak, mailtemplate)
    if template is None:
        pytest.skip(f"ZAC has no mailtemplate {mailtemplate}: add one in ZAC's beheer of mailtemplates")
    body = mail(zaak, onderwerp=template["onderwerp"], body=template["body"], createDocumentFromMail=True)
    fields = {"zaakOntvankelijk": ontvankelijk, "resultaatToelichting": "podiumd-tests", "restMailGegevens": body}
    response = user_event(zac, zac_url, str(zaak["uuid"]), "INTAKE_AFRONDEN", **fields)
    expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    return received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=str(body["ontvanger"]))


@pytest.mark.parametrize(
    ("ontvankelijk", "mailtemplate"),
    [(True, "ZAAK_ONTVANKELIJK"), (False, "ZAAK_NIET_ONTVANKELIJK")],
    ids=["ontvankelijk", "niet-ontvankelijk"],
)
@pytest.mark.scenario("""
    Given a new zaak in ZAC, in the intake
    When the behandelaar finishes the intake, ontvankelijk or not, with the mail of its mailtemplate
    Then the mail arrives
    And the zaak has the mail as a definitief PDF
    And the zaak stays open only when ontvankelijk
""")
def test_intake_mail_arrives_and_is_kept_as_a_definitief_pdf(  # the zaak, its mail and Mailpit
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    mail: Callable[..., JsonObject],
    mailpit: ApiClient,
    registry: ResourceRegistry,
    ontvankelijk: bool,  # noqa: FBT001  # a parameter of the test
    mailtemplate: str,
) -> None:
    """INTAKE_AFRONDEN with restMailGegevens of the mailtemplate, as ZAC's intake afronden dialog sends it."""
    zaak = zac_zaak()
    message = _intake_mail(zac, urls["zac"], zaak, mail, mailpit, registry, mailtemplate, ontvankelijk=ontvankelijk)
    stored = [item for item in zaak_documents(zac, urls["zac"], zaak) if item.get("titel") == message.get("Subject")]
    assert [(item.get("status"), item.get("formaat")) for item in stored] == [("definitief", "application/pdf")]
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is ontvankelijk


# Not strict: an estate that edited its ZAAK_ONTVANKELIJK mailtemplate hides the defect.
@pytest.mark.xfail(
    strict=False,
    reason="[zac-18] ZAC 5.9.1's default ZAAK_ONTVANKELIJK mailtemplate uses {zaaknummer} and {zaaktypenaam}, which ZAC "
    "does not fill in; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a new zaak in ZAC, in the intake
    When the behandelaar finishes the intake as ontvankelijk with the mail of its mailtemplate
    Then the mail has the zaak's data filled in, no variable names
""")
def test_ontvankelijk_mail_fills_in_its_variables(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    mail: Callable[..., JsonObject],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """The ontvankelijk mail's subject and body contain no {variable}."""
    zaak = zac_zaak()
    message = _intake_mail(zac, urls["zac"], zaak, mail, mailpit, registry, "ZAAK_ONTVANKELIJK", ontvankelijk=True)
    assert "{" not in f"{message.get('Subject')}{message.get('HTML')}"


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
