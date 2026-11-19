"""OMC informs an inwoner of their zaak through Notify, here the mock server."""

from __future__ import annotations

import time
import uuid

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.bootstrap.omc import LISTEN_PATH
from podiumd_tests.bootstrap.omc import omc_token
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import section
from podiumd_tests.mock_server import NOTIFY_EMAIL
from podiumd_tests.mock_server import NOTIFY_MESSAGEBOX
from podiumd_tests.mock_server import NOTIFY_SMS
from podiumd_tests.mock_server import Callback
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import delete_klantcontact_tree
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import partijen_of
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openklant import set_voorkeursadres
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

# Notify's delivery receipts (callbacks) to OMC.
CONFIRM_PATH = "/Notify/Confirm"
# Open Zaak, Open Notificaties and OMC each hand the event on in a background task.
MAIL_TIMEOUT = 120
# The Notify mock's path and the key of the address in OMC's request body.
EMAIL = (NOTIFY_EMAIL, "email_address")
SMS = (NOTIFY_SMS, "phone_number")
MESSAGEBOX = (NOTIFY_MESSAGEBOX, "recipient")
# OMC's whitelist value that allows every zaaktype identificatie.
EVERY = "*"


# The first OMC that reads an Open VTB 0.2.0 bericht (mijnOverheidBerichtenbox moved to the berichttype).
OMC_READS_NEW_OPENVTB = (2, 3, 2)
# The first OMC that keeps each request's notification to that request (QueryBase scoped, not a singleton).
OMC_REQUEST_SCOPED_QUERIES = (2, 4, 1)
# xdist_group of the tests that make OMC process notifications: older OMCs mix up concurrent ones (omc-8).
OMC_LISTEN = "omc-listen"


def make_inwoner(
    openklant: ApiClient, registry: ResourceRegistry, adres: str, *andere: str, bsn: str | None = None
) -> str:
    """Give a partij with this BSN (default a new one) these digitale adressen (e-mail addresses or phones); the BSN.

    With andere, adres is the voorkeursDigitaalAdres. Open Klant allows one partij per BSN: a partij of a BRP person
    that exists already gets the addresses, and cleanup restores its voorkeursDigitaalAdres.
    """
    bsn = bsn or random_bsn()
    partij = _partij_of(openklant, registry, bsn)
    make_digitaal_adres(openklant, registry, partij, adres)
    for ander in andere:
        make_digitaal_adres(openklant, registry, partij, ander, standaard=False)
    if andere:
        set_voorkeursadres(openklant, bsn, adres)
    return bsn


def _partij_of(openklant: ApiClient, registry: ResourceRegistry, bsn: str) -> JsonObject:
    """Return the partij with this BSN; a new one when Open Klant has none."""
    found = partijen_of(openklant, bsn)
    if not found:
        partij = make_partij(openklant, registry)
        make_partij_identificator(openklant, registry, partij, "bsn", bsn)
        return partij
    partij = openklant.get(found[0])
    voorkeur = partij.get("voorkeursDigitaalAdres")
    registry.add(
        f"voorkeursDigitaalAdres of {found[0]}", lambda: openklant.patch(found[0], {"voorkeursDigitaalAdres": voorkeur})
    )
    return partij


def make_inwoner_zaak(  # the zaak's clients and the addresses
    openzaak: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    adres: str,
    *andere: str,
) -> tuple[JsonObject, str]:
    """Create a zaak whose initiator is a new partij with these digitale adressen, as make_inwoner.

    Returns the zaak and the initiator's BSN.
    """
    bsn = make_inwoner(openklant, registry, adres, *andere)
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
    return zaak, bsn


def notify_request(env: Environment, channel: tuple[str, str], adres: str, template: str = "") -> JsonObject:
    """Return the mock server's record of OMC's Notify request to adres, with the template of OMC setting `template`.

    A Berichtenbox request has no template: leave `template` empty.
    """
    template_id = env.variable("omc", template) if template else None

    def is_wanted(entry: JsonObject) -> bool:
        body = section(entry, "body")
        return body.get(channel[1]) == adres and body.get("template_id") == template_id

    sent = template or channel[0]
    return Callback(env, channel[0]).wait_for(is_wanted, timeout=MAIL_TIMEOUT, description=f"OMC {sent} to {adres}")


def notify_bodies(env: Environment, channel: tuple[str, str], template: str) -> list[JsonObject]:
    """Return the bodies of all OMC's Notify requests on the channel with the template of OMC setting `template`."""
    template_id = env.variable("omc", template)
    bodies = (section(entry, "body") for entry in Callback(env, channel[0]).received())
    return [body for body in bodies if body.get("template_id") == template_id]


def confirm_delivery(http: requests.Session, env: Environment, sent: JsonObject, to: str, kind: str) -> None:
    """POST Notify's delivery receipt "delivered" for the sent notification (a mock server record) to OMC.

    kind: Notify's notification_type (email, sms, messagebox).
    """
    body = section(sent, "body")
    now = datetime.now(tz=UTC).isoformat()
    receipt = {
        "id": sent["id"],
        "reference": body["reference"],
        "to": to,
        "status": "delivered",
        "created_at": now,
        "completed_at": now,
        "sent_at": now,
        "notification_type": kind,
        "template_id": body.get("template_id"),
        "template_version": 1,
    }
    token = omc_token(env, time.time())
    url = env.profile.urls["omc"] + CONFIRM_PATH
    confirm = http.post(url, json=receipt, headers={"Authorization": f"Bearer {token}"})
    expect_status(confirm, HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.ACCEPTED)


def klantcontacten_about(openklant: ApiClient, object_id: str) -> list[JsonObject]:
    """Return the onderwerpobjecten in Open Klant whose objectId is object_id (a zaak or bericht uuid)."""
    found = openklant.list("onderwerpobjecten", {"onderwerpobjectidentificatorObjectId": object_id})
    # Checked here too: a filter the server ignored would match every onderwerpobject.
    return [item for item in found if section(item, "onderwerpobjectidentificator").get("objectId") == object_id]


def clean_up_klantcontacten(openklant: ApiClient, registry: ResourceRegistry, object_id: str) -> None:
    """Delete, at cleanup, the klantcontacten OMC registers about object_id."""

    def delete() -> None:
        for item in klantcontacten_about(openklant, object_id):
            delete_klantcontact_tree(openklant, str(section(item, "klantcontact").get("url")))

    registry.add(f"klantcontacten about {object_id}", delete)


def listen(http: requests.Session, env: Environment, body: object, issued: float | None = None) -> requests.Response:
    """POST a notification to OMC's Events/Listen with the token its abonnement uses, issued now unless given."""
    token = omc_token(env, time.time() if issued is None else issued)
    url = env.profile.urls["omc"] + LISTEN_PATH
    return http.post(url, json=body, headers={"Authorization": f"Bearer {token}"})


def listen_answers(env: Environment, resource_url: str) -> list[int | None]:
    """Return OMC's HTTP statuses to Open Notificaties' deliveries of the notification about resource_url.

    Oldest first; Open Notificaties logs them only with LOG_NOTIFICATIONS_IN_DB.
    """
    params: dict[str, object] = {"resource_url": resource_url, "callback_suffix": LISTEN_PATH}
    answers = run_snippet(env.kube, env.deployment_for("opennotificaties"), "opennotificaties_deliveries", params)
    return cast("list[int | None]", answers)


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
