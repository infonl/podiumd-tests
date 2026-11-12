"""ZAC: BAG objects chosen when a zaak is started; Open Zaak fetches each BAG URL to validate the zaakobject."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import BAG_DAM
from podiumd_tests.json_data import section
from podiumd_tests.responses import describe
from podiumd_tests.zac import bag_object
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import recent_zaken
from podiumd_tests.zac import start_zaak
from podiumd_tests.zac import zaak_bag_objecten
from podiumd_tests.zac import zaak_body

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

# A BAG URL on a host that never resolves (RFC 2606).
UNREACHABLE_BAG = "https://bag.example.invalid/adressen/0363200003761447"


@pytest.mark.source(
    "podiumd-tests", "ZAC team's regression scenarios: a BAG object chosen when the zaak is created is linked to it."
)
@pytest.mark.scenario("""
    Given the adres Dam 1 in Amsterdam in the BAG
    When the behandelaar starts a zaak in ZAC with that adres as BAG object
    Then the zaak lists the adres among its BAG objects
""")
def test_new_zaak_links_the_chosen_bag_adres(
    zac: requests.Session,
    urls: dict[str, str],
    zac_parameters: JsonObject,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """A BAG adres sent with a new zaak becomes its zaakobject.

    Open Zaak fetches the adres's URL from the BAG to validate the zaakobject.
    """
    adres = bag_object(zac, urls["zac"], "ADRES", BAG_DAM)
    body = zaak_body(zac_parameters, omschrijving=registry.tagged("zac-bag"))
    zaak = start_zaak(zac, urls["zac"], {**body, "bagObjecten": [adres]})
    clean_up_zaak(zac, urls["zac"], openzaak_productaanvraag, registry, zaak)
    linked = zaak_bag_objecten(zac, urls["zac"], zaak)
    assert [section(item, "zaakobject").get("identificatie") for item in linked] == [BAG_DAM]


@pytest.mark.source("podiumd-tests", "ZAC team's regression scenarios: a zaak ZAC refuses is not created.")
@pytest.mark.xfail(
    strict=True,
    reason="[zac-20] ZAC 5.9.1 creates a new zaak before its BAG objects and keeps it when Open Zaak refuses one; "
    "not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a BAG adres whose address Open Zaak cannot fetch
    When the behandelaar starts a zaak in ZAC with that adres as BAG object
    Then ZAC refuses the zaak
    And Open Zaak has no zaak of it
""")
def test_refused_bag_object_leaves_no_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_parameters: JsonObject,
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """The new zaak is refused with 400 and Open Zaak has no zaak with its omschrijving."""
    adres = {**bag_object(zac, urls["zac"], "ADRES", BAG_DAM), "url": UNREACHABLE_BAG}
    omschrijving = registry.tagged("zac-bag-onbereikbaar")
    body = {**zaak_body(zac_parameters, omschrijving=omschrijving), "bagObjecten": [adres]}
    refused = zac.post(f"{urls['zac']}/rest/zaken/zaak", json=body)
    left = [zaak for zaak in recent_zaken(openzaak_productaanvraag) if zaak.get("omschrijving") == omschrijving]
    for zaak in left:
        clean_up_zaak(zac, urls["zac"], openzaak_productaanvraag, registry, zaak)
    assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    assert [zaak["identificatie"] for zaak in left] == []
