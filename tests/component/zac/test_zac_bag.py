"""ZAC: the BAG objects and the locatie of a zaak; Open Zaak fetches each BAG URL to validate the zaakobject."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import BAG_DAM
from podiumd_tests.json_data import section
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import attempt_zaak
from podiumd_tests.zac import attribuut_historie
from podiumd_tests.zac import bag_object
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import koppel_bag_object
from podiumd_tests.zac import ontkoppel_bag_object
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import start_zaak
from podiumd_tests.zac import wijzig_zaak
from podiumd_tests.zac import zaak_bag_objecten
from podiumd_tests.zac import zaak_body
from podiumd_tests.zac import zaaklocatie

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

ZAC_TEAM = pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
)
# The Dam in Amsterdam as ZAC's locatie of a zaak, and as Open Zaak's historie shows it.
DAM = {"type": "POINT", "point": {"latitude": 52.37, "longitude": 4.89}}
DAM_WKT = "POINT(4.89 52.37)"

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
    body = {**zaak_body(zac_parameters, omschrijving=registry.tagged("zac-bag-onbereikbaar")), "bagObjecten": [adres]}
    refused, left = attempt_zaak(zac, urls["zac"], openzaak_productaanvraag, registry, body)
    assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    assert left == []


@ZAC_TEAM
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar sets its locatie to a point on the map, with a reden
    Then the zaak has that locatie
    When the behandelaar changes another field of the zaak
    Then the zaak keeps its locatie
    When the behandelaar removes the locatie with a reden
    Then the zaak has no locatie
    And the historie records the locatie set and removed, each with its reden
""")
def test_locatie_is_set_kept_and_removed_with_a_reden(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """PATCH zaaklocatie sets and clears zaakgeometrie; another edit keeps it; the historie has both with the reden."""
    zac_url, zaak = urls["zac"], zac_zaak()
    expect_status(zaaklocatie(zac, zac_url, zaak, DAM, "podiumd-tests gezet"), HTTPStatus.OK)
    assert read_zaak(zac, zac_url, str(zaak["uuid"])).get("zaakgeometrie") == DAM
    expect_status(wijzig_zaak(zac, zac_url, zaak, toelichting="podiumd-tests"), HTTPStatus.OK)
    assert read_zaak(zac, zac_url, str(zaak["uuid"])).get("zaakgeometrie") == DAM
    expect_status(zaaklocatie(zac, zac_url, zaak, None, "podiumd-tests weg"), HTTPStatus.OK)
    assert read_zaak(zac, zac_url, str(zaak["uuid"])).get("zaakgeometrie") is None
    assert attribuut_historie(zac, zac_url, zaak, "zaakgeometrie") == [
        (DAM_WKT, None, "podiumd-tests weg"),
        (None, DAM_WKT, "podiumd-tests gezet"),
    ]


@ZAC_TEAM
@pytest.mark.scenario("""
    Given the adres Dam 1 in Amsterdam in the BAG, and a zaak in ZAC
    When the behandelaar links the adres to the zaak, twice
    Then the zaak lists the adres once among its BAG objects
    When the behandelaar unlinks it with a reden
    Then the zaak lists no BAG object
    And the historie records the adres linked once and unlinked with the reden
""")
def test_bag_adres_is_linked_once_and_unlinked(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """POST /rest/bag twice gives one zaakobject; DELETE with redenWijzigen removes it; the historie has both.

    Open Zaak fetches the adres's URL from the BAG to validate the zaakobject.
    """
    zac_url, zaak = urls["zac"], zac_zaak()
    adres = bag_object(zac, zac_url, "ADRES", BAG_DAM)
    for _ in range(2):
        expect_status(koppel_bag_object(zac, zac_url, zaak, adres), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    linked = zaak_bag_objecten(zac, zac_url, zaak)
    assert [section(item, "zaakobject").get("identificatie") for item in linked] == [BAG_DAM]
    unlinked = ontkoppel_bag_object(zac, zac_url, zaak, linked[0], "podiumd-tests")
    expect_status(unlinked, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert zaak_bag_objecten(zac, zac_url, zaak) == []
    assert attribuut_historie(zac, zac_url, zaak, "objecttype.ADRES") == [
        (BAG_DAM, None, "podiumd-tests"),
        (None, BAG_DAM, ""),
    ]
