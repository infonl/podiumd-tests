"""ZAC's access to the BRP without the plus role brp_zoeken, through bootstrap's behandelaar test user (fixture zac_as)."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.json_data import section
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import POLICIES
from podiumd_tests.zac import person_key
from podiumd_tests.zac import send_with_person
from podiumd_tests.zac_betrokkenen import add_betrokkene
from podiumd_tests.zac_betrokkenen import betrokkene_roltype
from podiumd_tests.zac_betrokkenen import betrokkenen
from podiumd_tests.zac_betrokkenen import ontkoppel_betrokkene
from podiumd_tests.zac_betrokkenen import wijzig_initiator

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak", "pabc")]


@pytest.mark.source(POLICIES, "Without the plus role brp_zoeken a user cannot search the BRP, but can add a bedrijf.")
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype
    And a behandelaar without the plus role brp_zoeken
    When the behandelaar searches a person in the BRP
    Then ZAC refuses it
    When the behandelaar makes a bedrijf from the KvK the zaak's initiator
    Then the zaak has that bedrijf as initiator
""")
def test_without_brp_zoeken_no_person_search_but_a_bedrijf_initiator(
    zac_as: Callable[[str], requests.Session], urls: dict[str, str], bpmn_zaak: JsonObject
) -> None:
    """The behandelaar's person search answers 403; its initiator of type RSIN with a kvkNummer is stored."""
    behandelaar = zac_as("behandelaar")
    refused = behandelaar.put(f"{urls['zac']}/rest/klanten/personen", json={"bsn": EREBOS})
    assert refused.status_code == HTTPStatus.FORBIDDEN, describe(refused)
    bedrijf = {"type": "RSIN", "kvkNummer": KVK_TEST_NUMMER}
    changed = expect_status(wijzig_initiator(behandelaar, urls["zac"], bpmn_zaak, bedrijf, None), HTTPStatus.OK)
    assert section(changed.json(), "initiatorIdentificatie").get("kvkNummer") == KVK_TEST_NUMMER


@pytest.mark.source(
    POLICIES, "Without brp_zoeken a user still reads a person's details and removes a person from a zaak."
)
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype with a person from the BRP as betrokkene, added by the test admin
    And a behandelaar without the plus role brp_zoeken
    When the behandelaar opens the person's details
    Then ZAC shows them
    When the behandelaar removes the person from the zaak
    Then the zaak has no betrokkene left
""")
def test_without_brp_zoeken_person_details_and_removal(
    zac: requests.Session, zac_as: Callable[[str], requests.Session], urls: dict[str, str], bpmn_zaak: JsonObject
) -> None:
    """GET klanten/person checks no BRP right; verwijderenBetrokkene is a behandelaar right."""
    zac_url = urls["zac"]
    roltype = betrokkene_roltype(zac, zac_url, bpmn_zaak, "")
    added = send_with_person(
        zac, zac_url, EREBOS, lambda person: add_betrokkene(zac, zac_url, bpmn_zaak, roltype, person)
    )
    expect_status(added, HTTPStatus.OK)
    behandelaar = zac_as("behandelaar")
    shown = behandelaar.get(f"{zac_url}/rest/klanten/person/{person_key(zac, zac_url, EREBOS)}")
    assert expect_status(shown, HTTPStatus.OK).json().get("bsn") == EREBOS, describe(shown)
    betrokkene = betrokkenen(behandelaar, zac_url, bpmn_zaak)[0]
    expect_status(ontkoppel_betrokkene(behandelaar, zac_url, betrokkene, "podiumd-tests"), HTTPStatus.OK)
    assert betrokkenen(zac, zac_url, bpmn_zaak) == []
