"""Chain: a klantcontact in Open Klant linked to a zaak in Open Zaak, directly and through KISS.

Ported from TA regression 18 and KISS's AnonymousContactmomentZaakScenarios.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kcc import kiss_klantcontact
from podiumd_tests.kcc import kiss_klantcontacten
from podiumd_tests.kcc import kiss_onderwerpobject
from podiumd_tests.kcc import kiss_zaak
from podiumd_tests.kcc import kiss_zaken
from podiumd_tests.seed.openklant import ZAAK
from podiumd_tests.seed.openklant import klantcontact_body
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import make_onderwerpobject
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

KISS_E2E = "upstream KISS-frontend Kiss.Bff.EndToEndTest AnonymousContactmomentZaakScenarios"
KISS_REQUIRES = ("kiss", "keycloak", "openzaak", "openklant")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openzaak", "openklant"),
    pytest.mark.source(
        "TA regression/18-klantcontact-zaak-koppeling.spec.ts",
        "The KCC links a klantcontact to a zaak through an onderwerpobject, and the klantcontact shows that link.",
    ),
    pytest.mark.source(
        "TA interaction/20-klacht-journey-e2e.spec.ts",
        "Klacht journey: the KCC registers a klantcontact and links it to the inwoner's zaak.",
    ),
]


@pytest.mark.core
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When the KCC medewerker registers a klantcontact in Open Klant about the zaak
    Then the klantcontact shows the link to the zaak
    And the klantcontact is found by the zaak
""")
def test_klantcontact_about_a_zaak_is_found_by_the_zaak(
    openklant: ApiClient, openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """The KCC flow: a klantcontact linked to a zaak shows the link and is found by the zaak's uuid."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    klantcontact = make_klantcontact(openklant, registry)
    link = make_onderwerpobject(openklant, registry, klantcontact, str(zaak["uuid"]))
    read = openklant.get(f"klantcontacten/{klantcontact['uuid']}")
    assert [o["uuid"] for o in entries(read["gingOverOnderwerpobjecten"])] == [link["uuid"]]
    found = openklant.list("onderwerpobjecten", {"onderwerpobjectidentificatorObjectId": str(zaak["uuid"])})
    assert [o["uuid"] for o in found] == [link["uuid"]]


@pytest.mark.core
@pytest.mark.requires(*KISS_REQUIRES)
@pytest.mark.source(KISS_E2E, "The KCC finds a zaak by its zaaknummer and opens the zaak's page.")
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When the KCC medewerker searches KISS's zaken by the zaaknummer
    Then KISS finds exactly that zaak, with its zaaktype
    And KISS's page of the zaak shows its zaaknummer
""")
def test_kcc_finds_a_zaak_in_kiss_by_its_zaaknummer(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
) -> None:
    """GET /api/zaken/zaken?identificatie= finds the zaak with its _zaaktype; /api/zaken/zaken/{uuid} opens it."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    kiss = kiss_session(KCC)
    found = kiss_zaken(kiss, urls["kiss"], identificatie=str(zaak["identificatie"]))
    assert [(z.get("uuid"), section(z, "_zaaktype").get("url")) for z in found] == [(zaak["uuid"], parts.zaaktype)]
    assert kiss_zaak(kiss, urls["kiss"], str(zaak["uuid"])).get("identificatie") == zaak["identificatie"]


def _zaak_links(klantcontact: JsonObject) -> list[tuple[object, ...]]:
    """The (objectId, codeObjecttype, codeRegister, codeSoortObjectId) of each onderwerpobject a klantcontact is about."""
    keys = ("objectId", "codeObjecttype", "codeRegister", "codeSoortObjectId")
    return [
        tuple(section(link, "onderwerpobjectidentificator").get(key) for key in keys)
        for link in entries(section(klantcontact, "_expand").get("gingOverOnderwerpobjecten"))
    ]


@pytest.mark.core
@pytest.mark.requires(*KISS_REQUIRES)
@pytest.mark.source(KISS_E2E, "A contactmoment registered on a zaak in KISS shows on the zaak's Contactmomenten tab.")
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When the KCC medewerker registers a contactmoment on the zaak in KISS
    Then KISS lists the contactmoment on the zaak's Contactmomenten tab
    And the contactmoment is linked to the zaak as KISS records a zaak
""")
def test_contactmoment_on_a_zaak_in_kiss_is_listed_for_the_zaak(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    openklant: ApiClient,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    parts: ZaaktypeParts,
) -> None:
    """postklantcontacten with a zgw-Zaak onderwerpobject; KISS's klantcontacten by the zaak's uuid list it."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    kiss = kiss_session(KCC)
    body = klantcontact_body(registry, onderwerp=registry.tagged("kiss-zaak"))
    saved = kiss_klantcontact(kiss, urls["kiss"], openklant, registry, body)
    kiss_onderwerpobject(kiss, urls["kiss"], saved, zaak)
    listed = kiss_klantcontacten(
        kiss,
        urls["kiss"],
        onderwerpobject__onderwerpobjectidentificatorObjectId=str(zaak["uuid"]),
        expand="gingOverOnderwerpobjecten",
    )
    assert [(item.get("uuid"), _zaak_links(item)) for item in listed] == [(saved["uuid"], [(zaak["uuid"], *ZAAK)])]
