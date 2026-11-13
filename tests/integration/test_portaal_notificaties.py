"""Chain: a gemeente chooses who informs the burger of a zaak: the portal (Open Inwoner), the bronsysteem (OMC) or both.

Open Zaak → Open Notificaties → OMC → Notify (the mock server), and → Open Inwoner (abonnement: bootstrap wiring
openinwoner-notifications, or the environment owner's) → Mailpit. The portal's choice is per zaaktype: its statustype and informatieobjecttype
configuration in Open Inwoner. Open Inwoner mails no first status, so each test sets a second one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.oi_notifications import oi_notifications_missing
from podiumd_tests.bootstrap.omc import notify_mock_missing
from podiumd_tests.mailpit import forget_mails
from podiumd_tests.mailpit import own_address
from podiumd_tests.mailpit import quoted
from podiumd_tests.mailpit import received_message
from podiumd_tests.mailpit import search
from podiumd_tests.omc import EMAIL
from podiumd_tests.omc import MAIL_TIMEOUT
from podiumd_tests.omc import make_inwoner_zaak
from podiumd_tests.omc import notify_request
from podiumd_tests.openinwoner import configure_zaaktype
from podiumd_tests.openinwoner import make_account
from podiumd_tests.openinwoner import notification_outcome
from podiumd_tests.seed.catalogi import ZaaktypeTypes
from podiumd_tests.seed.catalogi import make_publishable_zaaktype
from podiumd_tests.seed.catalogi import publish
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import zaaktype_parts
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openinwoner", "omc", "openzaak", "openklant", "opennotificaties", "mailpit"),
]

# A status between the first and the eindstatus; informeren on each.
TYPES = ("Ontvangen", "In behandeling", "Afgehandeld")


@dataclass(frozen=True)
class InwonerZaak:
    """A zaak with its first status, whose initiator has a portal account and a digitaal adres in Open Klant."""

    parts: ZaaktypeParts
    zaak: JsonObject
    adres: str


@pytest.fixture(name="inwoner_zaak")
def fixture_inwoner_zaak(  # fixtures
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    openzaak: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    selectielijst_zaaktype: JsonObject,
    parts: ZaaktypeParts,
) -> Callable[..., InwonerZaak]:
    """make(portal): a zaak of a new zaaktype for which the portal's notifications are on or off."""
    need_bootstrap("openinwoner-zgw-group", "omc-abonnement", "infra-mock-server")
    reason = oi_notifications_missing(podiumd_env) or notify_mock_missing(podiumd_env)
    if reason:
        pytest.skip(reason)

    def make(*, portal: bool) -> InwonerZaak:
        types = ZaaktypeTypes(statustypen=TYPES, informeren=True, informatieobjecttypen=(parts.informatieobjecttype,))
        concept = make_publishable_zaaktype(podiumd_env, openzaak, registry, selectielijst_zaaktype, types)
        zaaktype = publish(openzaak, concept)
        configure_zaaktype(podiumd_env, registry, str(zaaktype["identificatie"]), notify=portal)
        own = zaaktype_parts(openzaak, zaaktype)
        adres = own_address(registry)
        forget_mails(podiumd_env, registry, f"to:{quoted(adres)}")
        zaak, bsn = make_inwoner_zaak(openzaak, openklant, registry, own, adres)
        make_account(podiumd_env, registry, bsn, adres)
        make_status(openzaak, zaak, str(own.statustypen[0]["url"]))
        return InwonerZaak(own, zaak, adres)

    return make


def portal_outcome(env: Environment, resource_url: str) -> str:
    """Open Inwoner's processing output once it handled the notification about the resource."""

    def handled() -> str | None:
        outcome = notification_outcome(env, resource_url)
        done = outcome and outcome["status"] in {"success", "failed", "skipped"}
        return str(outcome["output"] or outcome["error"]) if done and outcome else None

    return wait_until(handled, timeout=MAIL_TIMEOUT, interval=2, description=f"Open Inwoner handles {resource_url}")


@pytest.mark.tc("OI-043")
@pytest.mark.source("draaiboek OI-043", "A gemeente can choose to notify through the bronsysteem only.")
@pytest.mark.scenario("""
    Given a zaaktype whose status changes the portal does not report
    And a zaak of it whose initiator has a portal account and an e-mail address in Open Klant
    When the zaak gets its next status
    Then OMC asks Notify to send the zaak-updated e-mail
    And the portal handles the change without sending a mail
""")
def test_without_the_portal_only_omc_informs(
    podiumd_env: Environment, openzaak: ApiClient, mailpit: ApiClient, inwoner_zaak: Callable[..., InwonerZaak]
) -> None:
    """With the portal's notifications off for the zaaktype, only OMC informs the initiator of a status change."""
    made = inwoner_zaak(portal=False)
    status = make_status(openzaak, made.zaak, str(made.parts.statustypen[1]["url"]))
    notify_request(podiumd_env, EMAIL, made.adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKUPDATE")
    assert "'notify_status_change' is False" in portal_outcome(podiumd_env, str(status["url"]))
    assert search(mailpit, f"to:{quoted(made.adres)}") == []


@pytest.mark.tc("OI-041", "OI-044")
@pytest.mark.source("draaiboek OI-044", "A gemeente can choose to notify through both the portal and the bronsysteem.")
@pytest.mark.scenario("""
    Given a zaaktype whose status changes the portal reports
    And a zaak of it whose initiator has a portal account and an e-mail address in Open Klant
    When the zaak gets its next status
    Then OMC asks Notify to send the zaak-updated e-mail
    And the portal mails the initiator that the zaak was updated
""")
def test_portal_and_omc_both_inform(
    podiumd_env: Environment,
    openzaak: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    inwoner_zaak: Callable[..., InwonerZaak],
) -> None:
    """With the portal's notifications on for the zaaktype, both OMC and the portal inform of a status change."""
    made = inwoner_zaak(portal=True)
    make_status(openzaak, made.zaak, str(made.parts.statustypen[1]["url"]))
    notify_request(podiumd_env, EMAIL, made.adres, "NOTIFY_TEMPLATEID_EMAIL_ZAAKUPDATE")
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=made.adres)
    assert str(made.zaak["identificatie"]) in str(message["HTML"])


@pytest.mark.tc("OI-042")
@pytest.mark.source("draaiboek OI-042", "The portal notifies the burger of a new document on their zaak.")
@pytest.mark.scenario("""
    Given a zaaktype whose new documents the portal reports
    And a zaak of it whose initiator has a portal account
    When a definitive, public document is added to the zaak
    Then the portal mails the initiator that the zaak was updated
""")
def test_new_document_mails_through_the_portal(
    openzaak: ApiClient,
    mailpit: ApiClient,
    registry: ResourceRegistry,
    inwoner_zaak: Callable[..., InwonerZaak],
) -> None:
    """A definitive, public document on the zaak makes the portal mail the initiator."""
    made = inwoner_zaak(portal=True)
    document = make_document(openzaak, registry, made.parts.informatieobjecttype, status="definitief")
    link_document(openzaak, registry, made.zaak, document)
    message = received_message(mailpit, registry, timeout=MAIL_TIMEOUT, to=made.adres)
    assert str(made.zaak["identificatie"]) in str(message["HTML"])
