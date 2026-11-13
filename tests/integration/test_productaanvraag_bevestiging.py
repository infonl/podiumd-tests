"""Chain: ZAC mails an ontvangstbevestiging for a productaanvraag.

The anonymous submitter's mail uses the environment's own wiring (profile settings productaanvraag_type and
productaanvraag_zaaktype); the initiator's uses a throwaway zaaktype with a BRP koppeling, which an estate's zaaktype
can have off.
"""

from __future__ import annotations

import re
import secrets

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import KIERKEGAARD
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.zac import EMAIL_CONFIRMATION
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.mailpit import own_address
from podiumd_tests.mailpit import quoted
from podiumd_tests.mailpit import received_message
from podiumd_tests.mailpit import search
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.openklant import expanded
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import make_submission_contact
from podiumd_tests.seed.openklant import partijen_of
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import BEVESTIGING_NIET_VERSTUURD
from podiumd_tests.zac import E_FORMULIER
from podiumd_tests.zac import PRODUCTAANVRAAG_TIMEOUT
from podiumd_tests.zac import clean_up_inbox_entries
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import inbox_productaanvraag
from podiumd_tests.zac import mail_address
from podiumd_tests.zac import productaanvraag_zaak
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import read_zaakafhandelparameters
from podiumd_tests.zac import save_zaakafhandelparameters
from podiumd_tests.zac import start_zaak
from podiumd_tests.zac import zaak_body
from podiumd_tests.zac import zaak_with_contactgegevens
from podiumd_tests.zac_beheer import mailtemplate_named
from podiumd_tests.zac_documents import OPENBAAR_MAIL
from podiumd_tests.zac_documents import kept_mail

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
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
    Given an anonymous form's submitter left an e-mail address in Open Klant
    When the form's productaanvraag makes ZAC start a zaak
    Then the submitter receives a mail with the zaaknummer, from and with reply-to the zaaktype's afzenders
    And its salutation names no one
    And the zaak keeps the mail as a definitief, openbaar PDF/A
    And the zaak no longer has the indicatie that no bevestiging was sent
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
    """ZAC mails the zaaknummer to the address the submitter left, per the ZAPs' automaticEmailConfirmation.

    The productaanvraag has no betrokkenen, as Open Formulieren sends it for a form without login.
    """
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
    # ZAC leaves {ZAAK_INITIATOR} empty for a zaak without initiator.
    template = mailtemplate_named(zac, zac_url, str(bevestiging["templateName"]))
    aanhef = next(regel for regel in re.findall(r"<p>.*?</p>", str(template["body"])) if "{ZAAK_INITIATOR}" in regel)
    assert aanhef.replace("{ZAAK_INITIATOR}", "") in str(message.get("HTML"))
    assert kept_mail(zac, zac_url, zaak, message) == OPENBAAR_MAIL
    shown = read_zaak(zac, zac_url, str(zaak["uuid"]))
    assert BEVESTIGING_NIET_VERSTUURD not in strings(shown.get("indicaties"))


def own_productaanvraagtype(
    podiumd_env: Environment,
    zac: requests.Session,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
    **wanted: JsonObject,
) -> str:
    """Return a run-tagged productaanvraagtype of a throwaway zaaktype whose zaakafhandelparameters get wanted."""
    zac_url = podiumd_env.profile.urls["zac"]
    parameters = make_zac_zaaktype(podiumd_env, openzaak, registry, test_zaaktype)
    # ZAC refuses a productaanvraagtype that the zaakafhandelparameters of another zaaktype have.
    productaanvraagtype = registry.tagged(f"aanvraag-{secrets.token_hex(3)}")
    merged = {name: {**section(parameters, name), **value} for name, value in wanted.items()}
    saved = save_zaakafhandelparameters(
        zac, zac_url, {**parameters, **merged, "productaanvraagtype": productaanvraagtype}
    )
    # ZAC keeps the zaakafhandelparameters of a deleted zaaktype.
    registry.add(
        f"productaanvraagtype {productaanvraagtype}",
        lambda: save_zaakafhandelparameters(zac_as_admin(podiumd_env), zac_url, {**saved, "productaanvraagtype": None}),
    )
    return productaanvraagtype


@pytest.fixture(name="brp_productaanvraagtype")
def fixture_brp_productaanvraagtype(
    podiumd_env: Environment,
    zac: requests.Session,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
) -> str:
    """Return the productaanvraagtype of a throwaway zaaktype with BRP koppeling and ontvangstbevestiging."""
    return own_productaanvraagtype(
        podiumd_env,
        zac,
        openzaak,
        registry,
        test_zaaktype,
        betrokkeneKoppelingen={"brpKoppelen": True},
        automaticEmailConfirmation=dict(EMAIL_CONFIRMATION.wanted),
    )


@pytest.fixture(name="stil_productaanvraagtype")
def fixture_stil_productaanvraagtype(
    podiumd_env: Environment,
    zac: requests.Session,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
) -> str:
    """Return the productaanvraagtype of a throwaway zaaktype whose ontvangstbevestiging is off."""
    bevestiging = {**EMAIL_CONFIRMATION.wanted, "enabled": False}
    return own_productaanvraagtype(
        podiumd_env, zac, openzaak, registry, test_zaaktype, automaticEmailConfirmation=bevestiging
    )


@pytest.mark.requires("openklant", "mailpit", "keycloak", "pabc")
@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, betrokkenen-klant).",
)
@pytest.mark.scenario("""
    Given a zaaktype whose productaanvragen get an ontvangstbevestiging and a BRP koppeling
    And the initiator has two e-mail addresses in Open Klant, neither the voorkeur
    When a productaanvraag of the initiator makes ZAC start a zaak
    Then the ontvangstbevestiging goes to the address Open Klant lists first
    When the other address becomes the voorkeur and a second productaanvraag starts a zaak
    Then that ontvangstbevestiging goes to the voorkeur address
""")
def test_ontvangstbevestiging_goes_to_the_initiators_voorkeur_address_else_the_first(
    openzaak: ApiClient,
    objecten: ApiClient,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
    brp_productaanvraagtype: str,
) -> None:
    """ZAC mails the initiator's Open Klant e-mail address with isStandaardAdres, else the first."""
    partij = make_partij(openklant, registry)
    make_partij_identificator(openklant, registry, partij, "bsn", KIERKEGAARD)
    assert partijen_of(openklant, KIERKEGAARD) == [partij["url"]], f"other Open Klant partijen have BSN {KIERKEGAARD}"
    for _ in range(2):
        make_digitaal_adres(openklant, registry, partij, own_address(registry), standaard=False)
    adressen = expanded(openklant, str(partij["url"]), "digitaleAdressen")
    betrokkenen = [{"inpBsn": KIERKEGAARD, "rolOmschrijvingGeneriek": "initiator"}]

    def bevestigd_aan(adres: JsonObject, aanvraag: str) -> None:
        kenmerk = registry.tagged(aanvraag)
        make_productaanvraag(
            objecten, registry, productaanvraag_objecttype, brp_productaanvraagtype, kenmerk, betrokkenen=betrokkenen
        )
        zaak = productaanvraag_zaak(openzaak, registry, kenmerk)
        message = received_message(mailpit, registry, timeout=PRODUCTAANVRAAG_TIMEOUT, to=str(adres["adres"]))
        assert str(zaak["identificatie"]) in str(message.get("HTML"))

    bevestigd_aan(adressen[0], "zonder-voorkeur")
    openklant.patch(str(adressen[1]["url"]), {"isStandaardAdres": True})
    bevestigd_aan(adressen[1], "met-voorkeur")


# ZAC sends the ontvangstbevestiging right after it links the contactgegevens, in the same request.
BEVESTIGING_WAIT = 15


def is_left_unconfirmed(zac: requests.Session, zac_url: str, zaak: JsonObject) -> bool:
    """Whether the zaak keeps the indicatie that no bevestiging was sent, BEVESTIGING_WAIT seconds after ZAC linked
    the aanvraag's contactgegevens.
    """
    uuid = str(zaak["uuid"])
    zaak_with_contactgegevens(zac, zac_url, uuid)
    try:
        wait_until(
            lambda: BEVESTIGING_NIET_VERSTUURD not in strings(read_zaak(zac, zac_url, uuid).get("indicaties")),
            timeout=BEVESTIGING_WAIT,
            description=f"bevestiging of zaak {zaak['identificatie']}",
        )
    except WaitTimeoutError:
        return True
    return False


@pytest.mark.requires("openklant", "mailpit", "keycloak")
@pytest.mark.usefixtures("ontvangstbevestiging")
@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, other-api).",
)
@pytest.mark.scenario("""
    Given ZAC mails an ontvangstbevestiging for the productaanvragen of a zaaktype
    And an anonymous form's submitter left only a telefoonnummer in Open Klant
    When the form's productaanvraag makes ZAC start a zaak
    Then the zaak keeps the indicatie that no bevestiging was sent
""")
def test_without_an_e_mail_address_no_ontvangstbevestiging_is_sent(
    podiumd_env: Environment,
    zac: requests.Session,
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    productaanvraag_objecttype: str,
) -> None:
    """Without an aanvraagspecifiek or initiator e-mail address ZAC sends nothing and keeps the indicatie."""
    kenmerk = registry.tagged("zonder-adres")
    make_submission_contact(openklant, registry, kenmerk, "0612345678")
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, productaanvraagtype, kenmerk)
    zaak = productaanvraag_zaak(openzaak_productaanvraag, registry, kenmerk)
    assert is_left_unconfirmed(zac, podiumd_env.profile.urls["zac"], zaak)


@pytest.mark.requires("openklant", "mailpit", "keycloak", "pabc")
@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, other-api).",
)
@pytest.mark.scenario("""
    Given a zaaktype whose productaanvragen get no ontvangstbevestiging
    And a form's submitter left an e-mail address in Open Klant
    When the form's productaanvraag makes ZAC start a zaak
    Then the zaak keeps the indicatie that no bevestiging was sent
    And the submitter receives no mail
""")
def test_with_the_ontvangstbevestiging_off_no_mail_is_sent(
    podiumd_env: Environment,
    objecten: ApiClient,
    openzaak: ApiClient,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
    stil_productaanvraagtype: str,
) -> None:
    """With automaticEmailConfirmation off ZAC mails nothing to the aanvraagspecifiek address."""
    kenmerk = registry.tagged("bevestiging-uit")
    adres = own_address(registry)
    make_submission_contact(openklant, registry, kenmerk, adres)
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, stil_productaanvraagtype, kenmerk)
    zaak = productaanvraag_zaak(openzaak, registry, kenmerk)
    assert is_left_unconfirmed(zac_as_admin(podiumd_env), podiumd_env.profile.urls["zac"], zaak)
    assert search(mailpit, f"to:{quoted(adres)}") == []


@pytest.mark.requires("openklant", "mailpit", "keycloak")
@pytest.mark.usefixtures("ontvangstbevestiging")
@pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, other-api).",
)
@pytest.mark.scenario("""
    Given ZAC mails an ontvangstbevestiging for the productaanvragen of a zaaktype
    And a productaanvraag of a type no zaaktype handles, whose submitter left an e-mail address in Open Klant
    When the behandelaar starts a zaak of that zaaktype from it in the Inbox productaanvragen
    Then the zaak has the indicatie that no bevestiging was sent
    And the submitter receives no mail
""")
def test_zaak_from_the_inbox_productaanvragen_gets_no_ontvangstbevestiging(
    zac: requests.Session,
    urls: dict[str, str],
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    openklant: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
    zac_parameters: JsonObject,
) -> None:
    """ZAC links an inbox productaanvraag to the zaak it starts without mailing; the indicatie stays."""
    kenmerk = registry.tagged("inbox-bevestiging")
    adres = own_address(registry)
    clean_up_inbox_entries(zac, urls["zac"], registry, kenmerk)
    make_submission_contact(openklant, registry, kenmerk, adres)
    # As Open Formulieren sends it; without bijlagen ZAC 5.9.1 answers 500 (zac-36).
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, kenmerk, kenmerk, bijlagen=[])
    entry = inbox_productaanvraag(zac, urls["zac"], kenmerk)
    body = zaak_body(zac_parameters, omschrijving=kenmerk, communicatiekanaal=E_FORMULIER)
    zaak = start_zaak(zac, urls["zac"], {**body, "inboxProductaanvraag": entry})
    clean_up_zaak(zac, urls["zac"], openzaak_productaanvraag, registry, zaak)
    assert BEVESTIGING_NIET_VERSTUURD in strings(zaak.get("indicaties"))
    assert search(mailpit, f"to:{quoted(adres)}") == []
