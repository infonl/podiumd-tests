"""OMC informs an inwoner of their zaak through Notify, here the mock server."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.json_data import section
from podiumd_tests.mock_server import NOTIFY_EMAIL
from podiumd_tests.mock_server import NOTIFY_SMS
from podiumd_tests.mock_server import Callback
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

# Open Zaak, Open Notificaties and OMC each hand the event on in a background task.
MAIL_TIMEOUT = 120
# The Notify mock's path and the key of the address in OMC's request body.
EMAIL = (NOTIFY_EMAIL, "email_address")
SMS = (NOTIFY_SMS, "phone_number")


def make_inwoner_zaak(
    openzaak: ApiClient, openklant: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, adres: str
) -> tuple[JsonObject, str]:
    """Create a zaak whose initiator is a new partij with only this digitaal adres (an e-mail address or phone).

    Returns the zaak and the initiator's BSN.
    """
    bsn = random_bsn()
    partij = make_partij(openklant, registry)
    make_partij_identificator(openklant, registry, partij, "bsn", bsn)
    make_digitaal_adres(openklant, registry, partij, adres)
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
    return zaak, bsn


def notify_request(env: Environment, channel: tuple[str, str], adres: str, template: str) -> JsonObject:
    """Return the mock server's record of OMC's Notify request to adres with the template of OMC setting `template`."""
    template_id = env.variable("omc", template)

    def is_wanted(entry: JsonObject) -> bool:
        body = section(entry, "body")
        return body.get(channel[1]) == adres and body.get("template_id") == template_id

    return Callback(env, channel[0]).wait_for(is_wanted, timeout=MAIL_TIMEOUT, description=f"OMC {template} to {adres}")
