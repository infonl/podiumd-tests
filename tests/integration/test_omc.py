"""Chain: an inwoner's zaak reaches OMC, which informs the inwoner through Notify.

Open Zaak → Open Notificaties → OMC (abonnement: bootstrap wiring omc-abonnement) → Open Klant
(the inwoner's digitaal adres) → Notify, here the mock server; Notify's delivery receipt → OMC →
a klantcontact in Open Klant. TA's OMC specs check only OMC's API; these tests cover the whole chain.
They run only where OMC's Notify base URL is the mock server.
"""

from __future__ import annotations

import time
import uuid

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.omc import notify_mock_missing
from podiumd_tests.bootstrap.omc import omc_actor_missing
from podiumd_tests.bootstrap.omc import omc_setting
from podiumd_tests.bootstrap.omc import omc_token
from podiumd_tests.json_data import section
from podiumd_tests.mock_server import NOTIFY_EMAIL
from podiumd_tests.mock_server import NOTIFY_SMS
from podiumd_tests.mock_server import Callback
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import delete_klantcontact_tree
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import close_zaak
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("omc", "openzaak", "openklant", "opennotificaties")]

# Open Zaak, Open Notificaties and OMC each hand the event on in a background task.
MAIL_TIMEOUT = 120
# The Notify mock's path and the key of the address in OMC's request body.
EMAIL = (NOTIFY_EMAIL, "email_address")
SMS = (NOTIFY_SMS, "phone_number")


@pytest.fixture
def inwoner_zaak(
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    openzaak: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
) -> Callable[[tuple[str, str], str], JsonObject]:
    """A zaak whose initiator is a partij with only this digitaal adres (EMAIL or SMS)."""
    need_bootstrap("omc-abonnement", "infra-mock-server")
    if reason := notify_mock_missing(podiumd_env):
        pytest.skip(reason)

    def make(channel: tuple[str, str], adres: str) -> JsonObject:
        bsn = random_bsn()
        partij = make_partij(openklant, registry)
        make_partij_identificator(openklant, registry, partij, "bsn", bsn)
        make_digitaal_adres(openklant, registry, partij, adres)
        zaak = make_zaak(openzaak, registry, parts.zaaktype)
        make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
        return zaak

    return make


def notify_request(env: Environment, channel: tuple[str, str], adres: str, template: str) -> JsonObject:
    """The mock server's record of OMC's Notify request to adres with the template of OMC setting `template`."""
    template_id = omc_setting(env, template)

    def wanted(entry: JsonObject) -> bool:
        body = section(entry, "body")
        return body.get(channel[1]) == adres and body.get("template_id") == template_id

    return Callback(env, channel[0]).wait_for(wanted, timeout=MAIL_TIMEOUT, description=f"OMC {template} to {adres}")


def email_address(registry: ResourceRegistry) -> str:
    """A tagged address of this test only, which no one reads."""
    return f"{registry.tagged(f'omc-{uuid.uuid4().hex[:8]}')}@example.invalid"


def test_new_zaak_mails_the_initiator(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    inwoner_zaak: Callable[[tuple[str, str], str], JsonObject],
) -> None:
    """The first status of an inwoner's zaak makes OMC send the zaak-created e-mail."""
    adres = email_address(registry)
    make_status(openzaak, inwoner_zaak(EMAIL, adres), str(parts.statustypen[0]["url"]))
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKCREATE")


def test_next_status_mails_a_zaak_update(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    inwoner_zaak: Callable[[tuple[str, str], str], JsonObject],
) -> None:
    """A later status that does not close the zaak makes OMC send the zaak-updated e-mail."""
    assert len(parts.statustypen) >= 3, "the test zaaktype needs a status between the first and the eindstatus"
    adres = email_address(registry)
    zaak = inwoner_zaak(EMAIL, adres)
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKCREATE")
    make_status(openzaak, zaak, str(parts.statustypen[1]["url"]))
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKUPDATE")


def test_closing_the_zaak_mails_a_zaak_close(
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    inwoner_zaak: Callable[[tuple[str, str], str], JsonObject],
) -> None:
    """The eindstatus makes OMC send the zaak-closed e-mail."""
    adres = email_address(registry)
    zaak = inwoner_zaak(EMAIL, adres)
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKCREATE")
    close_zaak(openzaak, zaak, parts)
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKCLOSE")


def test_initiator_with_only_a_phone_number_gets_an_sms(
    podiumd_env: Environment,
    openzaak: ApiClient,
    parts: ZaaktypeParts,
    inwoner_zaak: Callable[[tuple[str, str], str], JsonObject],
) -> None:
    """An initiator whose only digitaal adres is a telefoonnummer gets the zaak-created SMS."""
    # In international form: OMC sends a national 06 number as +316.
    adres = f"+316{uuid.uuid4().int % 10**8:08d}"
    make_status(openzaak, inwoner_zaak(SMS, adres), str(parts.statustypen[0]["url"]))
    notify_request(podiumd_env, SMS, adres, "NOTIFY_TEMPLATEID_SMS_ZAAKCREATE")


def test_delivery_receipt_becomes_a_klantcontact(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    http: requests.Session,
    openzaak: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    inwoner_zaak: Callable[[tuple[str, str], str], JsonObject],
) -> None:
    """Notify's delivery receipt for OMC's mail makes OMC register a klantcontact about the zaak in Open Klant."""
    if reason := omc_actor_missing(podiumd_env, openklant):
        pytest.skip(reason)
    adres = email_address(registry)
    zaak = inwoner_zaak(EMAIL, adres)
    about = {"onderwerpobjectidentificatorObjectId": str(zaak["uuid"])}
    registry.add(
        f"klantcontacten about {zaak['uuid']}",
        lambda: [
            delete_klantcontact_tree(openklant, str(section(o, "klantcontact").get("url")))
            for o in openklant.list("onderwerpobjecten", about)
        ],
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
        podiumd_env.profile.urls["omc"] + "/Notify/Confirm", json=receipt, headers={"Authorization": f"Bearer {token}"}
    )
    expect_status(confirm, HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.ACCEPTED)
    wait_until(
        lambda: openklant.list("onderwerpobjecten", about),
        timeout=MAIL_TIMEOUT,
        description=f"klantcontact about zaak {zaak['identificatie']} in Open Klant",
    )
