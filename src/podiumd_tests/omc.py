"""OMC informs an inwoner of their zaak through Notify, here the mock server."""

from __future__ import annotations

import time
import uuid

from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.omc import omc_token
from podiumd_tests.json_data import section
from podiumd_tests.mock_server import NOTIFY_EMAIL
from podiumd_tests.mock_server import NOTIFY_SMS
from podiumd_tests.mock_server import Callback
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.zac import notificatie

if TYPE_CHECKING:
    import requests

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
# OMC's whitelist value that allows every zaaktype identificatie.
EVERY = "*"


# The first OMC that reads an Open VTB 0.2.0 bericht (mijnOverheidBerichtenbox moved to the berichttype).
OMC_READS_NEW_OPENVTB = (2, 3, 2)
# The first OMC that keeps each request's notification to that request (QueryBase scoped, not a singleton).
OMC_REQUEST_SCOPED_QUERIES = (2, 4, 1)
# xdist_group of the tests that make OMC process notifications: older OMCs mix up concurrent ones (omc-8).
OMC_LISTEN = "omc-listen"


def make_inwoner(openklant: ApiClient, registry: ResourceRegistry, adres: str) -> str:
    """Create a partij with a new BSN and only this digitaal adres (an e-mail address or phone); the BSN."""
    bsn = random_bsn()
    partij = make_partij(openklant, registry)
    make_partij_identificator(openklant, registry, partij, "bsn", bsn)
    make_digitaal_adres(openklant, registry, partij, adres)
    return bsn


def make_inwoner_zaak(
    openzaak: ApiClient, openklant: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, adres: str
) -> tuple[JsonObject, str]:
    """Create a zaak whose initiator is a new partij with only this digitaal adres (an e-mail address or phone).

    Returns the zaak and the initiator's BSN.
    """
    bsn = make_inwoner(openklant, registry, adres)
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


def notify_bodies(env: Environment, channel: tuple[str, str], template: str) -> list[JsonObject]:
    """Return the bodies of all OMC's Notify requests on the channel with the template of OMC setting `template`."""
    template_id = env.variable("omc", template)
    bodies = (section(entry, "body") for entry in Callback(env, channel[0]).received())
    return [body for body in bodies if body.get("template_id") == template_id]


def listen(http: requests.Session, env: Environment, body: object, issued: float | None = None) -> requests.Response:
    """POST a notification to OMC's Events/Listen with the token its abonnement uses, issued now unless given."""
    token = omc_token(env, time.time() if issued is None else issued)
    url = f"{env.profile.urls['omc']}/Events/Listen"
    return http.post(url, json=body, headers={"Authorization": f"Bearer {token}"})


def expect_outcome(response: requests.Response, status: int, reason: str) -> None:
    """Fail unless OMC answered status with reason in its statusDescription."""
    description = str(expect_status(response, status).json().get("statusDescription"))
    if reason not in description:
        msg = f"OMC answered {status} without {reason!r}: {description}"
        raise AssertionError(msg)


def is_listed(env: Environment, setting: str, value: str) -> bool:
    """Return whether OMC's comma-separated setting lists value or EVERY."""
    listed = {item.strip() for item in env.variable("omc", setting).split(",")}
    return value in listed or EVERY in listed


def setting_skip(env: Environment, setting: str, value: str, *, listed: bool) -> str | None:
    """Skip reason when OMC's setting does not list value (listed=True) or does (listed=False), else None."""
    if is_listed(env, setting, value) == listed:
        return None
    current = env.variable("omc", setting)
    return f"OMC's {setting} is {current!r}, which {'lacks' if listed else 'allows'} {value}"


def zaak_notificatie(zaak: JsonObject, resource: str, url: str) -> JsonObject:
    """Return the notificatie of a new resource (url) of the zaak, with the kenmerken OMC requires."""
    kenmerken = {key: zaak[key] for key in ("zaaktype", "bronorganisatie", "vertrouwelijkheidaanduiding")}
    return notificatie("zaken", resource, url, "create", hoofd_object=str(zaak["url"]), **kenmerken)


def besluit_notificatie(besluit: JsonObject, link: JsonObject) -> JsonObject:
    """Return the notificatie of a document linked to the besluit (link: the besluitinformatieobject)."""
    kenmerken = {key: besluit[key] for key in ("besluittype", "verantwoordelijkeOrganisatie")}
    besluit_url = str(besluit["url"])
    return notificatie(
        "besluiten", "besluitinformatieobject", str(link["url"]), "create", hoofd_object=besluit_url, **kenmerken
    )


def bericht_event(kind: str, bericht: str) -> JsonObject:
    """Return Open VTB's CloudEvent of this kind (bericht-gepubliceerd, ...) about the bericht (uuid)."""
    return {
        "specversion": "1.0",
        "type": f"nl.overheid.berichten.{kind}",
        "source": "urn:nld:openvtb",
        "id": str(uuid.uuid4()),
        "subject": bericht,
    }
