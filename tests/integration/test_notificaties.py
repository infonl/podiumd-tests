"""Chains: changes in Open Zaak and Open Klant reach subscribers through Open Notificaties.

Ported from TA regression 19, 25, 26, 27, 30, 33, 34, 37, 42, 45 and 46. Each test subscribes
callbacks of its own on the webhook receiver (infra/webhook-receiver) and matches the
notifications by their hoofdObject, so parallel tests and other subscribers do not interfere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.json_data import section
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.opennotificaties import make_abonnement
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.webhook import Callback

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openzaak", "opennotificaties")]

# Open Zaak and Open Klant send through a Celery task, and Open Notificaties delivers through another.
DELIVERY_TIMEOUT = 90
# The test catalogus's zaken and documenten only.
OWN = {"bronorganisatie": TEST_CATALOGUS_RSIN}


def event(kanaal: str, resource: str, actie: str, hoofd: object) -> Callable[[JsonObject], bool]:
    """Matches a received notification of this kind about hoofd (a URL)."""

    def match(entry: JsonObject) -> bool:
        body = entry.get("body")
        return (
            isinstance(body, dict)
            and body.get("kanaal") == kanaal
            and body.get("resource") == resource
            and body.get("actie") == actie
            and body.get("hoofdObject") == hoofd
        )

    return match


def notified(callback: Callback, match: Callable[[JsonObject], bool], description: str) -> JsonObject:
    """The body of the first matching notification the callback got."""
    return section(callback.wait_for(match, timeout=DELIVERY_TIMEOUT, description=description), "body")


@pytest.mark.core
def test_new_zaak_is_notified_to_a_subscriber(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    openzaak: ApiClient,
    opennotificaties: ApiClient,
    registry: ResourceRegistry,
    callback: Callback,
    test_zaaktype: JsonObject,
) -> None:
    """A subscriber on kanaal zaken gets the zaak's create notification with its zaaktype (TA reg-19)."""
    make_abonnement(opennotificaties, registry, callback.url, "zaken", OWN)
    zaak = make_zaak(openzaak, registry, str(test_zaaktype["url"]))
    notification = notified(callback, event("zaken", "zaak", "create", zaak["url"]), "the zaak's create notification")
    assert notification["resourceUrl"] == zaak["url"]
    assert section(notification, "kenmerken")["zaaktype"] == test_zaaktype["url"]


def test_kenmerk_filter_selects_the_subscriber(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    run_tag: str,
    openzaak: ApiClient,
    opennotificaties: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
    need_bootstrap: Callable[..., None],
) -> None:
    """Only the subscriber whose filter matches the vertrouwelijkheidaanduiding gets the zaak (TA reg-25)."""
    need_bootstrap("infra-webhook-receiver")
    openbaar, vertrouwelijk = Callback.new(podiumd_env, run_tag), Callback.new(podiumd_env, run_tag)
    for callback, va in ((openbaar, "openbaar"), (vertrouwelijk, "vertrouwelijk")):
        make_abonnement(opennotificaties, registry, callback.url, "zaken", {**OWN, "vertrouwelijkheidaanduiding": va})
    zaaktype = str(test_zaaktype["url"])
    open_zaak = make_zaak(openzaak, registry, zaaktype, vertrouwelijkheidaanduiding="openbaar")
    notified(openbaar, event("zaken", "zaak", "create", open_zaak["url"]), "the openbaar zaak")
    # A later zaak for the other subscriber: once it arrived, the first one would have too.
    secret = make_zaak(openzaak, registry, zaaktype, vertrouwelijkheidaanduiding="vertrouwelijk")
    notified(vertrouwelijk, event("zaken", "zaak", "create", secret["url"]), "the vertrouwelijk zaak")
    assert not [e for e in vertrouwelijk.received() if event("zaken", "zaak", "create", open_zaak["url"])(e)]


def test_every_subscriber_gets_the_notification(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    run_tag: str,
    openzaak: ApiClient,
    opennotificaties: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
    need_bootstrap: Callable[..., None],
) -> None:
    """Two subscribers on kanaal zaken (as ZAC and the portal) both get the same notification (TA reg-26)."""
    need_bootstrap("infra-webhook-receiver")
    callbacks = [Callback.new(podiumd_env, run_tag), Callback.new(podiumd_env, run_tag)]
    for callback in callbacks:
        make_abonnement(opennotificaties, registry, callback.url, "zaken", OWN)
    zaak = make_zaak(openzaak, registry, str(test_zaaktype["url"]))
    match = event("zaken", "zaak", "create", zaak["url"])
    first, second = (notified(c, match, "the zaak's create notification") for c in callbacks)
    core = ("kanaal", "resource", "actie", "hoofdObject", "resourceUrl", "kenmerken")
    assert {k: first[k] for k in core} == {k: second[k] for k in core}


def test_zaak_changes_are_notified_with_their_resource(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    openzaak: ApiClient,
    opennotificaties: ApiClient,
    registry: ResourceRegistry,
    callback: Callback,
    parts: ZaaktypeParts,
) -> None:
    """Status, rol, update, document link and rol removal of a zaak each reach kanaal zaken (TA reg-27, 30, 33, 34, 46)."""
    make_abonnement(opennotificaties, registry, callback.url, "zaken", OWN)
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    status = make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    rol = make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn="999990019")
    openzaak.patch(str(zaak["url"]), {"toelichting": registry.tagged("gewijzigd")})
    koppeling = link_document(openzaak, registry, zaak, make_document(openzaak, registry, parts.informatieobjecttype))
    openzaak.delete(str(rol["url"]))
    expected = [
        ("status", "create", status["url"]),
        ("rol", "create", rol["url"]),
        ("zaak", "partial_update", zaak["url"]),
        ("zaakinformatieobject", "create", koppeling["url"]),
        ("rol", "destroy", rol["url"]),
    ]
    for resource, actie, url in expected:
        notification = notified(callback, event("zaken", resource, actie, zaak["url"]), f"{resource} {actie}")
        assert notification["resourceUrl"] == url


def test_document_is_notified_on_kanaal_documenten(
    openzaak: ApiClient,
    opennotificaties: ApiClient,
    registry: ResourceRegistry,
    callback: Callback,
    parts: ZaaktypeParts,
) -> None:
    """A new document reaches kanaal documenten, apart from the zaken (TA reg-34)."""
    make_abonnement(opennotificaties, registry, callback.url, "documenten", OWN)
    document = make_document(openzaak, registry, parts.informatieobjecttype)
    match = event("documenten", "enkelvoudiginformatieobject", "create", document["url"])
    notified(callback, match, "the document's create notification")


@pytest.mark.requires("openklant")
def test_partij_changes_are_notified(
    openklant: ApiClient, opennotificaties: ApiClient, registry: ResourceRegistry, callback: Callback
) -> None:
    """Creating and changing a partij reach kanaal partijen (TA reg-37)."""
    make_abonnement(opennotificaties, registry, callback.url, "partijen", {})
    partij = make_partij(openklant, registry)
    openklant.patch(str(partij["url"]), {"indicatieActief": False})
    for actie in ("create", "partial_update"):
        notified(callback, event("partijen", "partij", actie, partij["url"]), f"partij {actie}")


@pytest.mark.requires("openklant")
def test_internetaak_changes_are_notified(
    openklant: ApiClient, opennotificaties: ApiClient, registry: ResourceRegistry, callback: Callback
) -> None:
    """Creating an internetaak and completing it reach kanaal internetaken (TA reg-45)."""
    make_abonnement(opennotificaties, registry, callback.url, "internetaken", {})
    taak = make_internetaak(openklant, registry, make_klantcontact(openklant, registry), [])
    openklant.patch(str(taak["url"]), {"status": "verwerkt"})
    for actie in ("create", "partial_update"):
        notified(callback, event("internetaken", "internetaak", actie, taak["url"]), f"internetaak {actie}")


def test_failed_delivery_is_retried(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    podiumd_env: Environment,
    run_tag: str,
    openzaak: ApiClient,
    opennotificaties: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
    need_bootstrap: Callable[..., None],
) -> None:
    """A subscriber that answers 500 gets the notification again and then accepts it (TA reg-42)."""
    need_bootstrap("infra-webhook-receiver")
    callback = Callback.new(podiumd_env, run_tag, fail_first=True)
    # A vertrouwelijkheidaanduiding no other test uses: another test's notification must not take the 500.
    only = {**OWN, "vertrouwelijkheidaanduiding": "beperkt_openbaar"}
    make_abonnement(opennotificaties, registry, callback.url, "zaken", only)
    zaak = make_zaak(openzaak, registry, str(test_zaaktype["url"]), vertrouwelijkheidaanduiding="beperkt_openbaar")
    match = event("zaken", "zaak", "create", zaak["url"])
    callback.wait_for(lambda e: match(e) and e.get("status") == 204, timeout=DELIVERY_TIMEOUT, description="redelivery")
    assert [e.get("status") for e in callback.received() if match(e)] == [500, 204]
