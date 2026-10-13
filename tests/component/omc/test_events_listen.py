"""OMC's Events/Listen recognizes a notification shaped as Open Notificaties sends it.

OMC answers 206 to a notification it cannot process, and Open Notificaties counts that as
delivered; the inner statusCode and details tell why. The notification is a new status, which OMC
handles (a new zaak is no OMC scenario: 206). With made-up uuids a recognized notification ends in
412 (OMC cannot fetch the status), a rejected one in 206.
"""

from __future__ import annotations

import time
import uuid

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.omc import omc_token
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.core, pytest.mark.requires("omc", "cluster")]


def notification(urls: dict[str, str], root: tuple[str, ...]) -> dict[str, object]:
    """A new-status notification for a zaak that does not exist, with Open Notificaties as these root properties."""
    zaken = urls["openzaak"] + "/zaken/api/v1/"
    body: dict[str, object] = {
        "kanaal": "zaken",
        "hoofdObject": f"{zaken}zaken/{uuid.uuid4()}",
        "resource": "status",
        "resourceUrl": f"{zaken}statussen/{uuid.uuid4()}",
        "actie": "create",
        "aanmaakdatum": datetime.now(tz=UTC).isoformat(),
        "kenmerken": {
            "bronorganisatie": "002220647",
            "zaaktype": f"{urls['openzaak']}/catalogi/api/v1/zaaktypen/{uuid.uuid4()}",
            "vertrouwelijkheidaanduiding": "openbaar",
        },
    }
    return body | dict.fromkeys(root, urls["opennotificaties"])


def listen(http: requests.Session, podiumd_env: Environment, body: dict[str, object]) -> requests.Response:
    """POST a notification to OMC's Events/Listen with the token its abonnement uses."""
    token = omc_token(podiumd_env, time.time())
    url = podiumd_env.profile.urls["omc"] + "/Events/Listen"
    return http.post(url, json=body, headers={"Authorization": f"Bearer {token}"})


@pytest.mark.parametrize(
    "root",
    [
        pytest.param((), id="without-source"),
        pytest.param(
            ("source",),
            id="as-opennotificaties",
            marks=pytest.mark.xfail(
                strict=True,
                reason="OMC 1.17.19 rejects the 'source' root property of Open Notificaties 1.16.2"
                " notifications (206, inner 422); not yet reported upstream",
            ),
        ),
    ],
)
def test_notification_is_recognized(
    http: requests.Session, podiumd_env: Environment, urls: dict[str, str], root: tuple[str, ...]
) -> None:
    """OMC processes the notification: 412, not the 206 that Open Notificaties would count as delivered."""
    expect_status(listen(http, podiumd_env, notification(urls, root)), HTTPStatus.PRECONDITION_FAILED)
