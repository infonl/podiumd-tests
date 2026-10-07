"""Chain: a productaanvraag in Objecten becomes a zaak through Open Notificaties and ZAC.

Merged from MK and PI test_productaanvraag_flow.py. It uses the environment's own wiring:
the Productaanvraag-Dimpact objecttype, the objecten kanaal and ZAC's zaakafhandelparameters
for profile settings productaanvraag_type and productaanvraag_zaaktype.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import PRODUCTAANVRAAG_OBJECTTYPE
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.objecten import objecttype_url
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.core,
    pytest.mark.requires("cluster", "objecten", "opennotificaties", "zac", "openzaak"),
]

# Objecten notifies, Open Notificaties delivers to ZAC, and ZAC starts the zaak and its case.
ZAAK_TIMEOUT = 120


@pytest.fixture(scope="module", name="productaanvraagtype")
def fixture_productaanvraagtype(podiumd_env: Environment) -> str:
    """The productaanvraagtype ZAC starts a zaak for; skips without the profile setting."""
    found = podiumd_env.profile.settings.get("productaanvraag_type")
    if not found:
        pytest.skip(f"profile {podiumd_env.profile.name} has no settings.productaanvraag_type")
    return found


@pytest.fixture(scope="module", name="objecttype")
def fixture_objecttype(podiumd_env: Environment) -> str:
    """The productaanvraag objecttype's URL as Objecten knows it."""
    return objecttype_url(podiumd_env, PRODUCTAANVRAAG_OBJECTTYPE)


def test_productaanvraag_becomes_a_zaak(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    objecten: ApiClient,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
    productaanvraagtype: str,
    objecttype: str,
) -> None:
    """ZAC starts a zaak for a new productaanvraag object and names its kenmerk in the toelichting."""
    kenmerk = registry.tagged("productaanvraag")
    make_productaanvraag(objecten, registry, objecttype, productaanvraagtype, kenmerk)

    def started() -> JsonObject | None:
        zaken = openzaak_productaanvraag.list(f"{ZAKEN}/zaken", {"startdatum": today()})
        return next((z for z in zaken if kenmerk in str(z.get("toelichting") or "")), None)

    zaak = wait_until(started, timeout=ZAAK_TIMEOUT, interval=3, description=f"zaak for productaanvraag {kenmerk}")
    url = str(zaak["url"])
    registry.add(f"zaak {url}", lambda: delete_zaak(openzaak_productaanvraag, url))
