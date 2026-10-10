"""Chain: a new zaak of an inwoner reaches OMC, which mails the inwoner through Notify.

Open Zaak → Open Notificaties → OMC (abonnement: bootstrap wiring omc-abonnement) → Open Klant
(the inwoner's e-mail address) → Notify, here the webhook receiver. TA's OMC specs check only
OMC's API; this is the chain PLAN.md lists as OMC → notify mock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import section
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.webhook import NOTIFY_EMAIL
from podiumd_tests.webhook import Callback

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("omc", "openzaak", "openklant", "opennotificaties")]

# Open Zaak, Open Notificaties and OMC each hand the event on in a background task.
MAIL_TIMEOUT = 120


@pytest.mark.xfail(
    strict=True,
    reason="OMC 1.17.19 (and 2.3.1) answers 206 'Required properties are missing' to every notification of "
    "Open Notificaties 1.16.2 / Open Zaak 1.29.3: it fails on their 'source' property, so it sends no mail; "
    "not yet reported upstream",
)
def test_new_zaak_mails_the_initiator(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    openzaak: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
) -> None:
    """The first status of an inwoner's zaak makes OMC send a zaak-created e-mail to the inwoner's address."""
    need_bootstrap("omc-abonnement", "infra-webhook-receiver")
    bsn = random_bsn()
    email = f"{registry.tagged('omc')}@example.invalid"
    partij = make_partij(openklant, registry)
    make_partij_identificator(openklant, registry, partij, "bsn", bsn)
    make_digitaal_adres(openklant, registry, partij, email)
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))

    def to_inwoner(entry: JsonObject) -> bool:
        return section(entry, "body").get("email_address") == email

    mail = Callback(podiumd_env, NOTIFY_EMAIL).wait_for(
        to_inwoner, timeout=MAIL_TIMEOUT, description=f"OMC mail to {email}"
    )
    assert section(mail, "body").get("template_id")
