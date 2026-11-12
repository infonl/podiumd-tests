"""ZAC: a medewerker allowed to search the BRP only for the gemeenten of a PABC domain."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.json_data import entries
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.zac_zaaktype import make_group_member
from podiumd_tests.seed.zac_zaaktype import make_other_domain_group
from podiumd_tests.zac import search_personen
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "keycloak", "pabc"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, betrokkenen-klant).",
    ),
]

# EREBOS's gemeente van inschrijving in the BRP test set, and another gemeente of that set.
EREBOS_GEMEENTE = {"code": "0530", "naam": "Hellevoetsluis"}
OTHER_GEMEENTE = "0518"


@pytest.mark.scenario("""
    Given a medewerker with brp_zoeken only in a PABC domain that holds one gemeente
    And raadpleger on a zaaktype of another domain
    Then ZAC offers that gemeente for BRP searches and requires a gemeente in each search
    When the medewerker searches a person by BSN in that gemeente
    Then ZAC finds the person
    When the medewerker searches in another gemeente, or without a gemeente
    Then ZAC refuses the search
""")
def test_brp_search_is_restricted_to_the_gemeenten_of_the_domain(
    podiumd_env: Environment, urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """personen/gemeenten lists the domain's gemeente; personen answers 200 there, 403 elsewhere (brp-rechten.rego)."""
    group = make_other_domain_group(
        podiumd_env, registry, "brp_zoeken", gemeenten={EREBOS_GEMEENTE["code"]: EREBOS_GEMEENTE["naam"]}
    )
    # ZAC lets in only a user with a role on a zaaktype; raadpleger there gives no BRP right.
    raadpleger = make_other_domain_group(podiumd_env, registry, "raadpleger")
    username, password = make_group_member(podiumd_env, registry, group, raadpleger)
    medewerker, zac_url = zac_session(podiumd_env, username, password), urls["zac"]

    assert get_entries(medewerker, f"{zac_url}/rest/klanten/personen/gemeenten") == [EREBOS_GEMEENTE]
    parameters = get_entries(medewerker, f"{zac_url}/rest/klanten/personen/parameters")
    assert {item.get("gemeenteVanInschrijving") for item in parameters} == {"REQ"}

    found = search_personen(medewerker, zac_url, bsn=EREBOS, gemeenteVanInschrijving=EREBOS_GEMEENTE["code"])
    assert [item.get("bsn") for item in entries(expect_status(found, HTTPStatus.OK).json().get("resultaten"))] == [
        EREBOS
    ]
    expect_status(search_personen(medewerker, zac_url, bsn=EREBOS, gemeenteVanInschrijving=OTHER_GEMEENTE), *REFUSED)
    expect_status(search_personen(medewerker, zac_url, bsn=EREBOS), *REFUSED)
