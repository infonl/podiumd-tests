"""Chain: an inwoner's zaak reaches OMC, which informs the inwoner through Notify.

Open Zaak → Open Notificaties → OMC (abonnement: bootstrap wiring omc-abonnement) → Open Klant
(the inwoner's digitaal adres) → Notify, here the mock server; Notify's delivery receipt → OMC →
a klantcontact in Open Klant. TA's OMC specs check only OMC's API; these tests cover the whole chain.
They run only where OMC's Notify base URL is the mock server.
"""

from __future__ import annotations

import dataclasses
import time

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.bootstrap.omc import notify_mock_missing
from podiumd_tests.bootstrap.omc import omc_actor_missing
from podiumd_tests.bootstrap.omc import omc_token
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.mailpit import own_address
from podiumd_tests.omc import EMAIL
from podiumd_tests.omc import MAIL_TIMEOUT
from podiumd_tests.omc import OMC_LISTEN
from podiumd_tests.omc import SMS
from podiumd_tests.omc import listen_answers
from podiumd_tests.omc import make_inwoner
from podiumd_tests.omc import make_inwoner_zaak
from podiumd_tests.omc import notify_request
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import delete_klantcontact_tree
from podiumd_tests.seed.openklant import random_phone_number
from podiumd_tests.seed.openklant import set_voorkeursadres
from podiumd_tests.seed.openzaak import close_zaak
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.zac_zaaktype import ZAC_TYPES
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac_productaanvraag import productaanvraag_zaak
from podiumd_tests.zac_productaanvraag import productaanvraag_zaaktype
from podiumd_tests.zac_productaanvraag import submit_digid_aanvraag

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("omc", "openzaak", "openklant", "opennotificaties"),
    pytest.mark.xdist_group(OMC_LISTEN),
    pytest.mark.source(
        "podiumd-tests",
        "TA's OMC specs check only OMC's API; these cover the chain from a zaak status through OMC and Notify back to Open Klant.",
    ),
]
# ZAC_TYPES whose statussen inform the initiator: OMC sends nothing for a status without informeren.
INFORMING_TYPES = dataclasses.replace(ZAC_TYPES, informeren=True)


def need_chain(podiumd_env: Environment, need_bootstrap: Callable[..., None], *steps: str) -> None:
    """Skip unless Open Notificaties delivers zaak events to OMC, OMC's Notify is the mock server, and steps are done."""
    need_bootstrap("omc-abonnement", "infra-mock-server", *steps)
    reason = notify_mock_missing(podiumd_env)
    if reason:
        pytest.skip(reason)


@pytest.fixture
def inwoner_zaak(
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    openzaak: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
) -> Callable[[str], JsonObject]:
    """A zaak whose initiator is a partij with only this digitaal adres (an e-mail address or phone number)."""
    need_chain(podiumd_env, need_bootstrap)
    return lambda adres: make_inwoner_zaak(openzaak, openklant, registry, parts, adres)[0]


@pytest.mark.requires("zac", "objecten", "openformulieren")
@pytest.mark.source(
    "PCP NotifyNL en Output Management Component, Testen van OMC",
    "A DigiD form's productaanvraag becomes a zaak that informs the inwoner at the voorkeursadres; after a switch "
    "of voorkeur, Intake afronden in ZAC informs at the other address.",
)
@pytest.mark.scenario("""
    Given an inwoner logged in with DigiD submits a form that registers a productaanvraag, e-mail preferred over phone
    When ZAC makes it a zaak of a zaaktype whose statussen inform, OMC sends the zaak-created e-mail to the e-mail
    When the inwoner prefers the phone and the behandelaar finishes the intake in ZAC
    Then OMC sends the zaak-updated SMS to the phone
    When the behandelaar closes the zaak in ZAC
    Then OMC sends the zaak-closed SMS to the phone
""")
def test_productaanvraag_zaak_informs_the_inwoner_at_the_voorkeursadres(  # the chain's clients
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    openzaak: ApiClient,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
    productaanvraag_objecttype: str,
) -> None:
    """OMC informs the productaanvraag's initiator at the voorkeursDigitaalAdres the partij has at each status."""
    need_chain(podiumd_env, need_bootstrap, "openformulieren-oidc-mock")
    zac_url, aanvraagtype = podiumd_env.profile.urls["zac"], registry.tagged("omc-aanvraag")
    zac = productaanvraag_zaaktype(
        podiumd_env, openzaak, registry, test_zaaktype, aanvraagtype=aanvraagtype, types=INFORMING_TYPES
    )
    email, phone = own_address(registry), random_phone_number()
    make_inwoner(openklant, registry, email, phone, bsn=EREBOS)
    aanvraag = submit_digid_aanvraag(
        podiumd_env, objecten, registry, objecttype=productaanvraag_objecttype, aanvraagtype=aanvraagtype, bsn=EREBOS
    )
    assert [betrokkene.get("inpBsn") for betrokkene in entries(aanvraag.get("betrokkenen"))] == [EREBOS]
    zaak = productaanvraag_zaak(openzaak, registry, str(section(aanvraag, "bron")["kenmerk"]))
    notify_request(podiumd_env, EMAIL, email, "NOTIFY_TEMPLATEID_EMAIL_ZAAKCREATE")
    set_voorkeursadres(openklant, EREBOS, phone)
    afronden_intake(zac, zac_url, zaak)
    notify_request(podiumd_env, SMS, phone, "NOTIFY_TEMPLATEID_SMS_ZAAKUPDATE")
    in_zac = read_zaak(zac, zac_url, str(zaak["uuid"]))
    expect_status(afhandelen(zac, zac_url, in_zac), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    notify_request(podiumd_env, SMS, phone, "NOTIFY_TEMPLATEID_SMS_ZAAKCLOSE")


@pytest.mark.scenario("""
    Given a zaak in Open Zaak whose initiator has an e-mail address in Open Klant
    When the zaak gets its first status and then its eindstatus
    Then OMC asks Notify to send the zaak-created and then the zaak-closed e-mail
""")
def test_closing_the_zaak_mails_a_zaak_close(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    inwoner_zaak: Callable[[str], JsonObject],
) -> None:
    """The eindstatus makes OMC send the zaak-closed e-mail."""
    adres = own_address(registry)
    zaak = inwoner_zaak(adres)
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKCREATE")
    close_zaak(openzaak, zaak, parts)
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKCLOSE")


@pytest.mark.scenario("""
    Given a zaak in Open Zaak whose initiator has only a telefoonnummer in Open Klant
    When the zaak gets its first status
    Then OMC asks Notify to send the inwoner the zaak-created SMS
""")
def test_initiator_with_only_a_phone_number_gets_an_sms(
    podiumd_env: Environment,
    openzaak: ApiClient,
    parts: ZaaktypeParts,
    inwoner_zaak: Callable[[str], JsonObject],
) -> None:
    """An initiator whose only digitaal adres is a telefoonnummer gets the zaak-created SMS."""
    adres = random_phone_number()
    make_status(openzaak, inwoner_zaak(adres), str(parts.statustypen[0]["url"]))
    notify_request(podiumd_env, SMS, adres, "NOTIFY_TEMPLATEID_SMS_ZAAKCREATE")


@pytest.mark.scenario("""
    Given OMC had Notify send the zaak-created e-mail for a zaak in Open Zaak
    When Notify reports to OMC that the e-mail was delivered
    Then OMC registers a klantcontact about the zaak in Open Klant
""")
def test_delivery_receipt_becomes_a_klantcontact(
    podiumd_env: Environment,
    http: requests.Session,
    openzaak: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    inwoner_zaak: Callable[[str], JsonObject],
) -> None:
    """Notify's delivery receipt for OMC's mail makes OMC register a klantcontact about the zaak in Open Klant."""
    reason = omc_actor_missing(podiumd_env, openklant)
    if reason:
        pytest.skip(reason)
    adres = own_address(registry)
    zaak = inwoner_zaak(adres)
    uuid = str(zaak["uuid"])

    def about_zaak() -> list[JsonObject]:
        # Checked here too: a filter the server ignored would match every onderwerpobject.
        found = openklant.list("onderwerpobjecten", {"onderwerpobjectidentificatorObjectId": uuid})
        return [o for o in found if section(o, "onderwerpobjectidentificator").get("objectId") == uuid]

    registry.add(
        f"klantcontacten about {uuid}",
        lambda: [delete_klantcontact_tree(openklant, str(section(o, "klantcontact").get("url"))) for o in about_zaak()],
    )
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    sent = notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKCREATE")
    body = section(sent, "body")
    now = datetime.now(tz=UTC).isoformat()
    receipt = {
        "id": sent["id"],
        "reference": body["reference"],
        "to": adres,
        "status": "delivered",
        "created_at": now,
        "completed_at": now,
        "sent_at": now,
        "notification_type": "email",
        "template_id": body["template_id"],
        "template_version": 1,
    }
    token = omc_token(podiumd_env, time.time())
    confirm = http.post(
        f"{podiumd_env.profile.urls['omc']}/Notify/Confirm", json=receipt, headers={"Authorization": f"Bearer {token}"}
    )
    expect_status(confirm, HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.ACCEPTED)
    wait_until(
        about_zaak,
        timeout=MAIL_TIMEOUT,
        description=f"klantcontact about zaak {zaak['identificatie']} in Open Klant",
    )


@pytest.mark.requires("cluster")
@pytest.mark.source(
    "upstream GemeenteNijmegen/mijn-services src/services/OpenKlantRegistrationService/README.md",
    "OMC can get a zaak's status before the initiator rol names the inwoner; only Open Notificaties' retry then"
    " delivers the mail.",
)
@pytest.mark.scenario("""
    Given an inwoner with an e-mail address in Open Klant
    And a zaak in Open Zaak without an initiator
    When the zaak gets its first status
    Then OMC refuses the notification because the zaak has no initiator
    When the inwoner becomes the zaak's initiator
    Then Open Notificaties delivers the notification again and OMC sends the zaak-created e-mail
""")
def test_initiator_added_after_the_first_status_still_gets_the_mail(
    podiumd_env: Environment,
    openzaak: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """OMC answers 412 to the status of a zaak without rollen; Open Notificaties' retry brings the mail after the rol."""
    need_chain(podiumd_env, need_bootstrap)
    adres = own_address(registry)
    bsn = make_inwoner(openklant, registry, adres)
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    status = str(make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))["url"])
    wait_until(
        lambda: HTTPStatus.PRECONDITION_FAILED in listen_answers(podiumd_env, status),
        timeout=MAIL_TIMEOUT,
        description=f"OMC's 412 to the status of zaak {zaak['identificatie']} in Open Notificaties' log",
    )
    make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKCREATE")
    assert listen_answers(podiumd_env, status)[-1] == HTTPStatus.ACCEPTED
