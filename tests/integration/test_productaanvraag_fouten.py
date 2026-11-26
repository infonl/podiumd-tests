"""ZAC's productaanvraag flow when something in the aanvraag or the zaaktype's configuration is off.

The cases come from Dimpact's analysis of failures in the productaanvraag flow (POO, 2025). Each test asserts
how the chain handles the case now; where the analysis named a wanted behaviour, that is what the chain does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.seed.objecten import make_productaanvraag
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.zac_zaaktype import ZAC_TYPES
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import NOTIFICATION_TIMEOUT
from podiumd_tests.zac import user_events_offered
from podiumd_tests.zac_documents import inbox_documenten
from podiumd_tests.zac_productaanvraag import productaanvraag_rollen
from podiumd_tests.zac_productaanvraag import productaanvraag_zaak
from podiumd_tests.zac_productaanvraag import productaanvraag_zaaktype

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("cluster", "objecten", "opennotificaties", "zac", "openzaak"),
]

# The page the cases come from.
FOUTAFHANDELING = "POO Foutafhandeling in de productaanvraag-flow - analyse"


def cmmn_aanvraagtype(
    env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    template: JsonObject,
    kenmerk: str,
    *,
    kvk: bool = True,
) -> tuple[requests.Session, str]:
    """Configure a throwaway CMMN zaaktype for the productaanvraagtype kenmerk; a ZAC admin session and the aanvraagtype.

    One aanvraagtype per test: ZAC links a productaanvraagtype to one zaaktype only.
    """
    zac = productaanvraag_zaaktype(env, openzaak, registry, template, aanvraagtype=kenmerk, types=ZAC_TYPES, kvk=kvk)
    return zac, kenmerk


def wait_for_process(zac: requests.Session, zac_url: str, zaak: JsonObject) -> None:
    """Wait until ZAC runs the CMMN process of the zaak: it offers the intake's user events."""
    wait_until(
        lambda: user_events_offered(zac, zac_url, str(zaak["uuid"])),
        timeout=NOTIFICATION_TIMEOUT,
        description=f"CMMN process of zaak {zaak['identificatie']}",
    )


@pytest.mark.source(
    FOUTAFHANDELING,
    "ZAC: the productaanvraag's document has an informatieobjecttype the zaaktype does not have (PZ-7622).",
)
@pytest.mark.scenario("""
    Given ZAC starts zaken of a CMMN zaaktype for a productaanvraagtype
    When a productaanvraag comes in whose PDF has an informatieobjecttype the zaaktype does not have
    Then ZAC starts the zaak and its process
    And the PDF is not linked to the zaak but stays in the Inbox documenten
""")
def test_document_of_another_informatieobjecttype_leaves_the_process_running(
    podiumd_env: Environment,
    openzaak: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
    parts: ZaaktypeParts,
    productaanvraag_objecttype: str,
) -> None:
    """A PDF of an informatieobjecttype the zaaktype lacks stays in the Inbox documenten; the zaak's process runs."""
    zac_url, kenmerk = podiumd_env.profile.urls["zac"], registry.tagged("vreemd-pdf")
    zac, aanvraagtype = cmmn_aanvraagtype(podiumd_env, openzaak, registry, test_zaaktype, kenmerk)
    # The test zaaktype's informatieobjecttype: the throwaway zaaktype has none.
    pdf = make_document(openzaak, registry, parts.informatieobjecttype, titel=kenmerk, bestandsnaam="aanvraag.pdf")
    make_productaanvraag(objecten, registry, productaanvraag_objecttype, aanvraagtype, kenmerk, pdf=pdf["url"])
    zaak = productaanvraag_zaak(openzaak, registry, kenmerk)
    wait_for_process(zac, zac_url, zaak)
    assert not openzaak.list(f"{ZAKEN}/zaakinformatieobjecten", {"zaak": str(zaak["url"])})
    wait_until(
        lambda: inbox_documenten(zac, zac_url, kenmerk),
        timeout=NOTIFICATION_TIMEOUT,
        description=f"{kenmerk} in ZAC's Inbox documenten",
    )


@pytest.mark.source(FOUTAFHANDELING, "ZAC: a betrokkene's KvK vestigingsnummer is not a valid vestigingsnummer.")
@pytest.mark.scenario("""
    Given the productaanvraag objecttype in Objecten
    When a form registers a productaanvraag that names a vestiging whose vestigingsnummer is not 12 digits
    Then Objecten refuses the productaanvraag for that vestigingsnummer
    And no invalid vestigingsnummer can reach ZAC
""")
def test_objecten_refuses_an_invalid_vestigingsnummer(
    objecten: ApiClient,
    registry: ResourceRegistry,
    productaanvraag_objecttype: str,
    productaanvraagtype: str,
) -> None:
    """The Productaanvraag-Dimpact objecttype refuses a vestigingsnummer of 5 digits, so ZAC never gets one."""
    betrokkene = {"vestigingsNummer": "12345", "rolOmschrijvingGeneriek": "initiator"}
    with pytest.raises(UnexpectedStatusError, match="'12345' does not"):
        make_productaanvraag(
            objecten,
            registry,
            productaanvraag_objecttype,
            productaanvraagtype,
            registry.tagged("vestigingsnummer"),
            betrokkenen=[betrokkene],
        )


@pytest.mark.source(
    FOUTAFHANDELING, "ZAC: a KvK betrokkene in the productaanvraag while the zaaktype's KvK koppeling is off."
)
@pytest.mark.scenario("""
    Given ZAC starts zaken of a CMMN zaaktype for a productaanvraagtype, with the BRP koppeling on and the KvK one off
    When a productaanvraag names a company from the KvK as initiator
    Then ZAC starts the zaak and its process
    And the zaak has no initiator from the productaanvraag
""")
def test_kvk_betrokkene_without_kvk_koppeling_still_starts_the_zaak(
    podiumd_env: Environment,
    openzaak: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
    productaanvraag_objecttype: str,
) -> None:
    """ZAC skips a KvK betrokkene the zaaktype may not link, instead of refusing the whole productaanvraag."""
    kenmerk = registry.tagged("zonder-kvk")
    zac, aanvraagtype = cmmn_aanvraagtype(podiumd_env, openzaak, registry, test_zaaktype, kenmerk, kvk=False)
    betrokkene = {"kvkNummer": KVK_TEST_NUMMER, "rolOmschrijvingGeneriek": "initiator"}
    make_productaanvraag(
        objecten, registry, productaanvraag_objecttype, aanvraagtype, kenmerk, betrokkenen=[betrokkene]
    )
    zaak = productaanvraag_zaak(openzaak, registry, kenmerk)
    wait_for_process(zac, podiumd_env.profile.urls["zac"], zaak)
    assert productaanvraag_rollen(openzaak, zaak) == set()
