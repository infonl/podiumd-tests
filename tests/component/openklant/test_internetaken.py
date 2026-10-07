"""Open Klant internetaken: assignment to actors, filters and validation.

Ported from TA interaction 145 and regression 112 and 157 (KI-060).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openklant")]


@pytest.mark.parametrize(
    "soorten",
    [
        ["medewerker"],
        ["organisatorische_eenheid"],
        ["geautomatiseerde_actor"],
        ["organisatorische_eenheid", "medewerker"],
    ],
    ids=["medewerker", "afdeling", "systeem", "afdeling-en-medewerker"],
)
def test_internetaak_assigned_to_actors(openklant: ApiClient, registry: ResourceRegistry, soorten: list[str]) -> None:
    """An internetaak keeps the actors it is assigned to (TA reg-112)."""
    actoren = [make_actor(openklant, registry, soort) for soort in soorten]
    taak = make_internetaak(openklant, registry, make_klantcontact(openklant, registry), actoren)
    assigned = entries(openklant.get(str(taak["url"]))["toegewezenAanActoren"])
    assert sorted(str(a["uuid"]) for a in assigned) == sorted(str(a["uuid"]) for a in actoren)


@pytest.mark.core
def test_internetaak_found_by_its_klantcontact(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """The aanleidinggevendKlantcontact filter finds the internetaak (TA int-145)."""
    klantcontact = make_klantcontact(openklant, registry)
    taak = make_internetaak(openklant, registry, klantcontact, [make_actor(openklant, registry)])
    found = openklant.list("internetaken", {"aanleidinggevendKlantcontact__uuid": str(klantcontact["uuid"])})
    assert [t["uuid"] for t in found] == [taak["uuid"]]


def test_internetaak_without_klantcontact_is_refused(openklant: ApiClient) -> None:
    """An internetaak needs an aanleidinggevend klantcontact (TA reg-157 KI-060)."""
    body = {
        "nummer": "1",
        "gevraagdeHandeling": "x",
        "toegewezenAanActoren": [],
        "toelichting": "x",
        "status": "te_verwerken",
    }
    openklant.request("POST", "internetaken", 400, json=body)
