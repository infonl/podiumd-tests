"""OMC's Events/Listen recognizes a notification shaped as Open Notificaties sends it.

OMC answers 206 to a notification it cannot process, and Open Notificaties counts that as
delivered; the inner statusCode and details tell why. The notification is a new status, which OMC
handles (a new zaak is no OMC scenario: 206). With made-up uuids a recognized notification ends in
412 (OMC cannot fetch the status), a rejected one in 206.
"""

from __future__ import annotations

import time
import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.omc import VALIDITY
from podiumd_tests.omc import OMC_LISTEN
from podiumd_tests.omc import listen
from podiumd_tests.omc import zaak_notificatie
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

pytestmark = [
    pytest.mark.component,
    pytest.mark.core,
    pytest.mark.requires("omc", "cluster"),
    pytest.mark.xdist_group(OMC_LISTEN),
]


def notification(urls: dict[str, str], root: tuple[str, ...]) -> JsonObject:
    """A new-status notification for a zaak that does not exist, with Open Notificaties as these root properties."""
    zaak = {
        "url": f"{urls['openzaak']}/{ZAKEN}/zaken/{uuid.uuid4()}",
        "zaaktype": f"{urls['openzaak']}/{CATALOGI}/zaaktypen/{uuid.uuid4()}",
        "bronorganisatie": "002220647",
        "vertrouwelijkheidaanduiding": "openbaar",
    }
    body = zaak_notificatie(zaak, "status", f"{urls['openzaak']}/{ZAKEN}/statussen/{uuid.uuid4()}")
    return {**body, **dict.fromkeys(root, urls["opennotificaties"])}


@pytest.mark.parametrize(
    "root",
    [
        pytest.param((), id="without-source"),
        pytest.param(
            ("source",),
            id="as-opennotificaties",
            marks=pytest.mark.xfail(
                strict=True,
                reason="[omc-1] OMC 1.17.19 and 2.3.1 reject the 'source' root property of Open Notificaties 1.16.2"
                " notifications (206, inner 422); not yet reported upstream",
            ),
        ),
    ],
)
@pytest.mark.source(
    "podiumd-tests", "OMC answers 206 to a notification it cannot process, which Open Notificaties counts as delivered."
)
@pytest.mark.scenario("""
    Given a notification of a new status for a zaak that does not exist
    And the notification with or without Open Notificaties' source property
    When it is posted to OMC with the token of OMC's abonnement
    Then OMC processes it and fails only on fetching the unknown status
""")
def test_notification_is_recognized(
    http: requests.Session, podiumd_env: Environment, urls: dict[str, str], root: tuple[str, ...]
) -> None:
    """OMC processes the notification: 412, not the 206 that Open Notificaties would count as delivered."""
    expect_status(listen(http, podiumd_env, notification(urls, root)), HTTPStatus.PRECONDITION_FAILED)


@pytest.mark.source(
    "upstream Worth-NL/NotifyNL-OMC OMC/Tests/Infrastructure/WebApi/EventsHandler.IntegrationTests/Controllers/EventsControllerTests.cs",
    "Listen_WithExpiredToken_Returns401: OMC refuses a notification whose token has expired.",
)
@pytest.mark.scenario("""
    Given a notification of a new status
    And a token signed with OMC's secret that expired a day ago
    When the notification is posted to OMC with that token
    Then OMC refuses it as unauthorized
""")
def test_expired_token_is_refused(http: requests.Session, podiumd_env: Environment, urls: dict[str, str]) -> None:
    """A token that expired a day ago gets 401, though OMC's own secret signed it."""
    expired = time.time() - VALIDITY - 24 * 3600
    expect_status(listen(http, podiumd_env, notification(urls, ()), issued=expired), HTTPStatus.UNAUTHORIZED)
