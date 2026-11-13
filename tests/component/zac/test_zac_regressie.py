"""One CMMN zaak in ZAC through the steps of the ZAC team's old regression run, while Aanvullende informatie is open."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import BAG_DAM
from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.zac_zaaktype import ZAC_TYPES
from podiumd_tests.zac import DAM
from podiumd_tests.zac import GERELATEERD
from podiumd_tests.zac import bag_object
from podiumd_tests.zac import koppel
from podiumd_tests.zac import koppel_bag_object
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import send_with_person
from podiumd_tests.zac import zaak_bag_objecten
from podiumd_tests.zac import zaak_status
from podiumd_tests.zac import zaaklocatie
from podiumd_tests.zac_betrokkenen import add_betrokkene
from podiumd_tests.zac_betrokkenen import betrokkene_roltype
from podiumd_tests.zac_betrokkenen import betrokkenen
from podiumd_tests.zac_documents import document_url
from podiumd_tests.zac_documents import nieuwe_versie
from podiumd_tests.zac_documents import uploaded_document
from podiumd_tests.zac_taken import complete_task

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    # Fixture zac_taken_zaaktype: a throwaway zaaktype made known to PABC, one per run.
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster"),
    pytest.mark.xdist_group("zac-taken-zaaktype"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, taken-cmmn):"
        " aanvullende informatie with betrokkenen, BAG object, zaak koppelen, locatie, new version and ondertekenen.",
    ),
]


@pytest.mark.scenario("""
    Given a zaak in its intake in ZAC with the taak Aanvullende informatie open, and another zaak
    When the behandelaar adds a person as belanghebbende, links the adres Dam 1 and sets the locatie on the Dam
    And links the other zaak as gerelateerd
    And adds a new version of a PDF on the zaak and ondertekent it
    And completes the taak
    Then the zaak is back in its intake and keeps the belanghebbende, the adres, the locatie and the gerelateerde zaak
    And the PDF keeps the new version's beschrijving, and is definitief and ondertekend
""")
def test_aanvullende_informatie_zaak_keeps_every_change(
    zac: requests.Session,
    urls: dict[str, str],
    zac_taken_zaak: Callable[[], JsonObject],
    start_taak: Callable[..., JsonObject],
    registry: ResourceRegistry,
) -> None:
    """Betrokkene, BAG object, locatie, gerelateerde zaak, nieuwe versie and ondertekenen on one zaak with an open taak."""
    zac_url = urls["zac"]
    zaak, ander = zac_taken_zaak(), zac_taken_zaak()
    taak = start_taak(zaak)

    roltype = betrokkene_roltype(zac, zac_url, zaak, "belanghebbende")
    added = send_with_person(zac, zac_url, EREBOS, lambda persoon: add_betrokkene(zac, zac_url, zaak, roltype, persoon))
    expect_status(added, HTTPStatus.OK)
    adres = bag_object(zac, zac_url, "ADRES", BAG_DAM)
    expect_status(koppel_bag_object(zac, zac_url, zaak, adres), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    expect_status(zaaklocatie(zac, zac_url, zaak, DAM, "podiumd-tests"), HTTPStatus.OK)
    expect_status(koppel(zac, zac_url, zaak, ander, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    document = uploaded_document(zac, zac_url, zaak, registry, suffix="pdf", status="in_bewerking")
    expect_status(nieuwe_versie(zac, zac_url, zaak, document, {"beschrijving": "tweede versie"}), HTTPStatus.OK)
    url, of_zaak = document_url(zac_url, document), {"zaak": str(zaak["uuid"])}
    expect_status(zac.post(f"{url}/onderteken", params=of_zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    complete_task(zac, zac_url, taak, {"aanvullendeInformatie": "podiumd-tests"})

    assert zaak_status(zac, zac_url, zaak) == ZAC_TYPES.statustypen[0]
    assert [str(item.get("roltype")) for item in betrokkenen(zac, zac_url, zaak)] == [roltype["naam"]]
    assert [section(item, "zaakobject").get("identificatie") for item in zaak_bag_objecten(zac, zac_url, zaak)] == [
        BAG_DAM
    ]
    gelezen = read_zaak(zac, zac_url, str(zaak["uuid"]))
    gerelateerd = [
        (item.get("identificatie"), item.get("relatieType")) for item in entries(gelezen["gerelateerdeZaken"])
    ]
    assert (gelezen.get("zaakgeometrie"), gerelateerd) == (DAM, [(ander["identificatie"], GERELATEERD)])
    ondertekend = expect_status(zac.get(url, params=of_zaak), HTTPStatus.OK).json()
    # Ondertekenen saves one more version.
    assert (ondertekend["versie"], ondertekend["status"]) == (int(str(document["versie"])) + 2, "definitief")
    assert ondertekend["beschrijving"] == "tweede versie"
    assert "ONDERTEKEND" in strings(ondertekend.get("indicaties"))
