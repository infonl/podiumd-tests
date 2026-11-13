"""OMC's scenarios beyond the zaak status: besluit genomen and taak toegewezen, and when OMC sends nothing.

Each notification goes straight to OMC's Events/Listen, shaped as Open Notificaties delivers it: OMC's abonnement
covers kanaal zaken only. OMC answers with its outcome: 202 when it sent, 206 when it stopped, with the reason.
A case that needs an OMC setting the environment does not have skips and names the setting.
"""

from __future__ import annotations

import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import BERICHT_OBJECTTYPE
from podiumd_tests.bootstrap.names import BERICHT_OBJECTTYPE_UUID
from podiumd_tests.bootstrap.names import TAAK_OBJECTTYPE
from podiumd_tests.bootstrap.names import TAAK_OBJECTTYPE_UUID
from podiumd_tests.bootstrap.names import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.omc import notify_mock_missing
from podiumd_tests.json_data import section
from podiumd_tests.mailpit import own_address
from podiumd_tests.omc import EMAIL
from podiumd_tests.omc import besluit_notificatie
from podiumd_tests.omc import expect_outcome
from podiumd_tests.omc import listen
from podiumd_tests.omc import make_inwoner_zaak
from podiumd_tests.omc import notify_request
from podiumd_tests.omc import setting_skip
from podiumd_tests.omc import zaak_notificatie
from podiumd_tests.seed.catalogi import ZaaktypeTypes
from podiumd_tests.seed.catalogi import make_publishable_zaaktype
from podiumd_tests.seed.catalogi import publish
from podiumd_tests.seed.objecten import created_notificatie
from podiumd_tests.seed.objecten import make_object
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import link_besluit_document
from podiumd_tests.seed.openzaak import make_besluit
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.seed.openzaak import zaaktype_parts
from podiumd_tests.zac import notificatie

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
    pytest.mark.requires("omc", "openzaak", "cluster"),
]

DOCS = "upstream Worth-NL/NotifyNL-OMC omc-notify.gitbook.io"
STOPPED = HTTPStatus.PARTIAL_CONTENT
SENT = "The notification has been successfully processed and sent to Notify NL"
NOT_WHITELISTED = f"case type with identification {TEST_ZAAKTYPE!r} is not included in the"
DECISION_IOTS = "ZGW_VARIABLE_OBJECTTYPE_DECISIONINFOOBJECTTYPE_UUIDS"
TASK_OBJECTTYPE = "ZGW_VARIABLE_OBJECTTYPE_TASKOBJECTTYPE_UUID"
MESSAGE_OBJECTTYPE = "ZGW_VARIABLE_OBJECTTYPE_MESSAGEOBJECTTYPE_UUID"
# A document OMC tells the inwoner about.
OPENBAAR_DEFINITIEF = {"status": "definitief", "vertrouwelijkheidaanduiding": "openbaar"}


@pytest.fixture(name="notify_mock")
def fixture_notify_mock(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> None:
    """Skip unless OMC's Notify is the mock server."""
    need_bootstrap("infra-mock-server")
    reason = notify_mock_missing(podiumd_env)
    if reason:
        pytest.skip(reason)


@pytest.mark.source(DOCS, "An event that matches no scenario is answered without a notification.")
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When OMC gets the notification that the zaak was created
    Then OMC answers that it does not know what to do with it
""")
def test_event_without_a_scenario_is_skipped(
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
) -> None:
    """A new zaak is no OMC scenario: 206, no notification."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    response = listen(http, podiumd_env, zaak_notificatie(zaak, "zaak", str(zaak["url"])))
    expect_outcome(response, STOPPED, "It was not possible to determine what to do with the received notification")


@pytest.mark.source(DOCS, "OMC informs the inwoner of a status only when its statustype has informeren.")
@pytest.mark.scenario("""
    Given a zaak of a zaaktype whose statustypen do not inform the initiator
    When OMC gets the notification of the zaak's first status
    Then OMC stops because the statustype has informeren off
""")
def test_status_without_informeren_is_not_mailed(
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    selectielijst_zaaktype: JsonObject,
    parts: ZaaktypeParts,
) -> None:
    """A status of a statustype with informeren false: 206 with that reason."""
    types = ZaaktypeTypes(informatieobjecttypen=(parts.informatieobjecttype,))
    concept = make_publishable_zaaktype(podiumd_env, openzaak, registry, selectielijst_zaaktype, types)
    own = zaaktype_parts(openzaak, publish(openzaak, concept))
    zaak = make_zaak(openzaak, registry, own.zaaktype)
    status = make_status(openzaak, zaak, str(own.statustypen[0]["url"]))
    response = listen(http, podiumd_env, zaak_notificatie(zaak, "status", str(status["url"])))
    expect_outcome(response, STOPPED, "the inform field in the case type is set to false")


@pytest.mark.xfail(
    strict=True,
    reason="[omc-4] OMC 2.3.1 answers 412 to an Objecten notification of an objecttype it does not handle while "
    "ZGW_VARIABLE_OBJECTTYPE_PRINTOBJECTTYPE_UUID is empty (the chart default), instead of 206; not yet reported upstream",
)
@pytest.mark.source(DOCS, "Only the objecttypen OMC is configured with (taak, bericht, KTO, print) start a scenario.")
@pytest.mark.scenario("""
    Given an object of an objecttype that OMC does not know
    When OMC gets the notification that the object was created
    Then OMC stops because the objecttype is none of its own
""")
def test_object_of_another_objecttype_is_not_mailed(
    http: requests.Session, podiumd_env: Environment, urls: dict[str, str]
) -> None:
    """An object of an unknown objecttype: 206 naming OMC's objecttype settings."""
    url = f"{urls['objecten']}/api/v2/objects/{uuid.uuid4()}"
    objecttype = f"{urls['objecttypen']}/api/v2/objecttypes/{uuid.uuid4()}"
    response = listen(http, podiumd_env, notificatie("objecten", "object", url, "create", objectType=objecttype))
    expect_outcome(response, STOPPED, "Check respective whitelist")


def besluit_document(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, zaak: JsonObject, **document: object
) -> JsonObject:
    """Make a besluit on the zaak with a document of these fields; the notificatie of the document's link."""
    besluit = make_besluit(openzaak, registry, parts.besluittype, zaak=zaak["url"])
    made = make_document(openzaak, registry, parts.informatieobjecttype, "podiumd-tests", **document)
    return besluit_notificatie(besluit, link_besluit_document(openzaak, registry, besluit, made))


def informatieobjecttype_skip(env: Environment, parts: ZaaktypeParts, *, listed: bool) -> None:
    """Skip unless OMC's DECISION_IOTS lists (listed) or lacks the test zaaktype's informatieobjecttype."""
    reason = setting_skip(env, DECISION_IOTS, parts.informatieobjecttype.rsplit("/", 1)[1], listed=listed)
    if reason:
        pytest.skip(reason)


@pytest.mark.source(DOCS, "Besluit genomen: only a document of a configured informatieobjecttype is told.")
@pytest.mark.scenario("""
    Given a besluit on a zaak with a document of an informatieobjecttype OMC is not configured with
    When OMC gets the notification that the document was linked to the besluit
    Then OMC stops because of the informatieobjecttype
""")
def test_besluit_document_of_another_informatieobjecttype_is_not_mailed(
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
) -> None:
    """A besluit document of an informatieobjecttype not in OMC's list: 206 naming that setting."""
    informatieobjecttype_skip(podiumd_env, parts, listed=False)
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    notification = besluit_document(openzaak, registry, parts, zaak, **OPENBAAR_DEFINITIEF)
    expect_outcome(listen(http, podiumd_env, notification), STOPPED, f"is not included in the: {DECISION_IOTS}")


@pytest.mark.source(DOCS, "Besluit genomen: only a definitief and openbaar document is told.")
@pytest.mark.parametrize(
    ("document", "reason"),
    [
        pytest.param({"status": "in_bewerking"}, "the status of the decision is not definitive", id="not-definitief"),
        pytest.param(
            {"status": "definitief", "vertrouwelijkheidaanduiding": "vertrouwelijk"},
            "because of the confidentiality setting",
            id="not-openbaar",
        ),
    ],
)
@pytest.mark.scenario("""
    Given a besluit on a zaak with a document that is not definitief, or not openbaar
    When OMC gets the notification that the document was linked to the besluit
    Then OMC stops because of the document's status or vertrouwelijkheid
""")
def test_besluit_document_not_for_the_inwoner_is_not_mailed(
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    document: dict[str, object],
    reason: str,
) -> None:
    """A besluit document that is not definitief, or not openbaar: 206 with that reason."""
    informatieobjecttype_skip(podiumd_env, parts, listed=True)
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    notification = besluit_document(openzaak, registry, parts, zaak, **document)
    expect_outcome(listen(http, podiumd_env, notification), STOPPED, reason)


@pytest.mark.source(DOCS, "Besluit genomen: only for a zaaktype in ZGW_WHITELIST_DECISIONMADE_IDS.")
@pytest.mark.scenario("""
    Given a besluit with a definitief, openbaar document on a zaak of a zaaktype OMC does not whitelist for besluiten
    When OMC gets the notification that the document was linked to the besluit
    Then OMC stops because of the zaaktype
""")
def test_besluit_of_a_zaaktype_not_whitelisted_is_not_mailed(
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
) -> None:
    """A besluit on a zaak of a zaaktype not in ZGW_WHITELIST_DECISIONMADE_IDS: 206 with that reason."""
    informatieobjecttype_skip(podiumd_env, parts, listed=True)
    reason = setting_skip(podiumd_env, "ZGW_WHITELIST_DECISIONMADE_IDS", TEST_ZAAKTYPE, listed=False)
    if reason:
        pytest.skip(reason)
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    notification = besluit_document(openzaak, registry, parts, zaak, **OPENBAAR_DEFINITIEF)
    expect_outcome(listen(http, podiumd_env, notification), STOPPED, NOT_WHITELISTED)


@pytest.mark.requires("objecten", "openklant")
@pytest.mark.usefixtures("notify_mock")
@pytest.mark.source(DOCS, "Besluit genomen: OMC tells the initiator of a besluit with a definitief, openbaar document.")
@pytest.mark.scenario("""
    Given a zaak whose initiator is known in Open Klant
    And a besluit on the zaak with a definitief, openbaar document
    When OMC gets the notification that the document was linked to the besluit
    Then OMC stores a bericht about the besluit for the initiator, worded by Notify's besluit template
""")
def test_besluit_becomes_a_bericht_for_the_initiator(
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    openklant: ApiClient,
    objecten: ApiClient,
    need_bootstrap: Callable[..., None],
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
) -> None:
    """A definitief, openbaar besluit document makes OMC store a bericht in Objecten (OMC 2.3.1 sends no mail)."""
    informatieobjecttype_skip(podiumd_env, parts, listed=True)
    reason = setting_skip(podiumd_env, "ZGW_WHITELIST_DECISIONMADE_IDS", TEST_ZAAKTYPE, listed=True)
    reason = reason or setting_skip(podiumd_env, MESSAGE_OBJECTTYPE, BERICHT_OBJECTTYPE_UUID, listed=True)
    if reason:
        pytest.skip(reason)
    need_bootstrap("objecttypen-bericht")
    zaak, _ = make_inwoner_zaak(openzaak, openklant, registry, parts, own_address(registry))
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    notification = besluit_document(openzaak, registry, parts, zaak, **OPENBAAR_DEFINITIEF)
    berichttype = objecttype_url(podiumd_env, BERICHT_OBJECTTYPE)
    stored = {"type": berichttype, "data_attr": f"referentie__exact__{notification['hoofdObject']}"}
    registry.add(
        f"OMC's bericht about {notification['hoofdObject']}",
        lambda: [objecten.delete(str(bericht["url"])) for bericht in objecten.list("objects", stored)],
    )
    expect_outcome(listen(http, podiumd_env, notification), HTTPStatus.ACCEPTED, SENT)
    template = podiumd_env.variable("omc", "NOTIFY_TEMPLATEID_DECISIONMADE")
    berichten = [section(section(bericht, "record"), "data") for bericht in objecten.list("objects", stored)]
    assert [bericht.get("onderwerp") for bericht in berichten] == [f"ptest preview {template}"]


@pytest.fixture(name="taak_objecttype")
def fixture_taak_objecttype(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> str:
    """Return the URL Objecten knows bootstrap's taak objecttype by; skip unless it is OMC's taak objecttype."""
    reason = setting_skip(podiumd_env, TASK_OBJECTTYPE, TAAK_OBJECTTYPE_UUID, listed=True)
    if reason:
        pytest.skip(reason)
    need_bootstrap("objecttypen-taak")
    return objecttype_url(podiumd_env, TAAK_OBJECTTYPE)


def make_taak(
    objecten: ApiClient, registry: ResourceRegistry, objecttype: str, zaak: JsonObject, status: str, bsn: str
) -> JsonObject:
    """Create a taak object (The Hague's schema, which OMC reads) for the BSN on the zaak; its notificatie."""
    data = {
        "title": registry.tagged("taak"),
        "status": status,
        "verloopdatum": f"{today()}T23:59:00Z",
        "identificatie": {"type": "bsn", "value": bsn},
        "zaak": zaak["url"],
    }
    return created_notificatie(make_object(objecten, registry, objecttype, data))


@pytest.mark.requires("objecten")
@pytest.mark.source(DOCS, "Taak toegewezen: only an open taak is told.")
@pytest.mark.scenario("""
    Given a closed taak for an inwoner on a zaak
    When OMC gets the notification that the taak was created
    Then OMC stops because the taak is not open
""")
def test_closed_taak_is_not_mailed(
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    taak_objecttype: str,
) -> None:
    """A taak with status gesloten: 206 with that reason."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    notification = make_taak(objecten, registry, taak_objecttype, zaak, "gesloten", random_bsn())
    expect_outcome(listen(http, podiumd_env, notification), STOPPED, "the task is already closed")


@pytest.mark.requires("objecten")
@pytest.mark.source(DOCS, "Taak toegewezen: only for a zaaktype in ZGW_WHITELIST_TASKASSIGNED_IDS.")
@pytest.mark.scenario("""
    Given an open taak for an inwoner on a zaak of a zaaktype OMC does not whitelist for taken
    When OMC gets the notification that the taak was created
    Then OMC stops because of the zaaktype
""")
def test_taak_of_a_zaaktype_not_whitelisted_is_not_mailed(
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    taak_objecttype: str,
) -> None:
    """An open taak on a zaak of a zaaktype not in ZGW_WHITELIST_TASKASSIGNED_IDS: 206 with that reason."""
    reason = setting_skip(podiumd_env, "ZGW_WHITELIST_TASKASSIGNED_IDS", TEST_ZAAKTYPE, listed=False)
    if reason:
        pytest.skip(reason)
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    notification = make_taak(objecten, registry, taak_objecttype, zaak, "open", random_bsn())
    expect_outcome(listen(http, podiumd_env, notification), STOPPED, NOT_WHITELISTED)


@pytest.mark.requires("objecten", "openklant")
@pytest.mark.usefixtures("notify_mock")
@pytest.mark.source(DOCS, "Taak toegewezen: OMC tells the inwoner of an open taak on a whitelisted zaaktype.")
@pytest.mark.scenario("""
    Given a zaak whose initiator has an e-mail address in Open Klant
    And an open taak for the initiator on the zaak
    When OMC gets the notification that the taak was created
    Then OMC asks Notify to send the initiator the taak e-mail
""")
def test_taak_is_mailed_to_the_inwoner(
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
    taak_objecttype: str,
) -> None:
    """An open taak for the initiator makes OMC send the taak e-mail."""
    reason = setting_skip(podiumd_env, "ZGW_WHITELIST_TASKASSIGNED_IDS", TEST_ZAAKTYPE, listed=True)
    if not reason and not podiumd_env.variable("omc", "NOTIFY_TEMPLATEID_EMAIL_TASKASSIGNED"):
        reason = "OMC's NOTIFY_TEMPLATEID_EMAIL_TASKASSIGNED is empty"
    if reason:
        pytest.skip(reason)
    adres = own_address(registry)
    zaak, bsn = make_inwoner_zaak(openzaak, openklant, registry, parts, adres)
    make_status(openzaak, zaak, str(parts.statustypen[0]["url"]))
    notification = make_taak(objecten, registry, taak_objecttype, zaak, "open", bsn)
    expect_outcome(listen(http, podiumd_env, notification), HTTPStatus.ACCEPTED, SENT)
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_TASKASSIGNED")
