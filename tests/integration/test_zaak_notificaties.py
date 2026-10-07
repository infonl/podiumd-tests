"""Chain: a zaak created in Open Zaak reaches a subscriber through Open Notificaties. Ported from TA regression 19."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.json_data import section
from podiumd_tests.seed.opennotificaties import make_abonnement
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry
    from podiumd_tests.webhook import Callback

pytestmark = [pytest.mark.integration, pytest.mark.requires("openzaak", "opennotificaties")]

# Open Zaak sends notifications through a Celery task, and Open Notificaties delivers through another.
DELIVERY_TIMEOUT = 90


def test_new_zaak_is_notified_to_a_subscriber(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    openzaak: ApiClient,
    opennotificaties: ApiClient,
    registry: ResourceRegistry,
    callback: Callback,
    test_zaaktype: JsonObject,
) -> None:
    """A subscriber on kanaal zaken gets the zaak's create notification with its zaaktype (TA reg-19)."""
    make_abonnement(opennotificaties, registry, callback.url, "zaken", {"bronorganisatie": TEST_CATALOGUS_RSIN})
    zaak = make_zaak(openzaak, registry, str(test_zaaktype["url"]))

    def is_create(entry: JsonObject) -> bool:
        body = entry.get("body")
        return isinstance(body, dict) and body.get("resourceUrl") == zaak["url"] and body.get("actie") == "create"

    notification = section(
        callback.wait_for(is_create, timeout=DELIVERY_TIMEOUT, description="the zaak's create notification"), "body"
    )
    assert notification["kanaal"] == "zaken"
    assert notification["resource"] == "zaak"
    assert notification["hoofdObject"] == zaak["url"]
    assert section(notification, "kenmerken")["zaaktype"] == test_zaaktype["url"]
