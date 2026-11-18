"""Open Klant klantcontacten: CRUD, filters, actors and betrokkenen.

Ported from TA interaction 09 and regression 86, 87 and 149.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.seed.openklant import expanded
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_betrokkene
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import ref

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openklant")]


@pytest.mark.core
@pytest.mark.source(
    "TA interaction/09-ok2-klantcontact.spec.ts",
    "A klantcontact registered through the Open Klant Klantinteracties API reads back the same record.",
)
@pytest.mark.source(
    "TA regression/87-ok2-klantcontact-zoeken.spec.ts",
    "A klantcontact's full record can be retrieved, so a question and answer can be consulted.",
)
@pytest.mark.source(
    "TA regression/87-ok2-klantcontact-zoeken.spec.ts",
    "The KCC can list klantcontacten (paginated) and search them on kanaal.",
)
@pytest.mark.source(
    "TA regression/149-ok2-crud-uitbreiding.spec.ts",
    "A klantcontact's onderwerp can be changed after registration, and a wrongly registered one deleted.",
)
@pytest.mark.scenario("""
    Given a klantcontact on kanaal balie is registered in Open Klant
    When it is read back
    Then it has the kanaal, onderwerp and contact-gelukt indication it was registered with, and a nummer
    And the paginated list with a total count, filtered on kanaal balie, finds it
    When its onderwerp and inhoud are changed and it is deleted
    Then Open Klant returns the changed onderwerp and inhoud, and then answers 404 for it
""")
def test_klantcontact_lifecycle(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """A klantcontact reads back with a nummer, is found by kanaal, changes with PATCH and goes with DELETE."""
    created = make_klantcontact(openklant, registry, kanaal="balie")
    url = str(created["url"])
    read = openklant.get(url)
    assert (read["kanaal"], read["onderwerp"], read["indicatieContactGelukt"]) == ("balie", created["onderwerp"], True)
    assert read["nummer"]
    page = openklant.get("klantcontacten", {"pageSize": "5", "kanaal": "balie", "onderwerp": str(created["onderwerp"])})
    assert isinstance(page["count"], int)
    assert [k["uuid"] for k in entries(page["results"])] == [created["uuid"]]
    changed = openklant.patch(url, {"onderwerp": registry.tagged("gewijzigd"), "inhoud": "gewijzigd"})
    assert (changed["onderwerp"], changed["inhoud"]) == (registry.tagged("gewijzigd"), "gewijzigd")
    openklant.delete(url)
    openklant.request("GET", url, 404)


@pytest.mark.source(
    "TA interaction/09-ok2-klantcontact.spec.ts",
    "A klantcontact can be linked to the KCC medewerker who registered it.",
)
@pytest.mark.scenario("""
    Given a klantcontact and a medewerker in Open Klant
    When the medewerker is linked to the klantcontact as actor
    Then the klantcontact shows exactly that medewerker as betrokken actor
""")
def test_actor_linked_to_klantcontact(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """A medewerker linked through actorklantcontacten shows in hadBetrokkenActoren (TA int-09)."""
    actor = make_actor(openklant, registry)
    klantcontact = make_klantcontact(openklant, registry)
    link = openklant.post("actorklantcontacten", {"klantcontact": ref(klantcontact), "actor": ref(actor)})
    registry.add("actorklantcontact", lambda: openklant.delete(str(link["url"])))
    actors = entries(openklant.get(str(klantcontact["url"]))["hadBetrokkenActoren"])
    assert [a["uuid"] for a in actors] == [actor["uuid"]]


@pytest.mark.source(
    "TA regression/87-ok2-klantcontact-zoeken.spec.ts",
    "Open Klant expands a klantcontact's betrokkenen for the KCC context.",
)
@pytest.mark.scenario("""
    Given a klantcontact in Open Klant with an anonymous betrokkene
    When the klantcontact is read with its betrokkenen expanded
    Then it holds that betrokkene with its contactnaam
""")
def test_expand_had_betrokkenen(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """expand=hadBetrokkenen inlines an anonymous betrokkene (TA reg-87)."""
    klantcontact = make_klantcontact(openklant, registry)
    betrokkene = make_betrokkene(openklant, registry, klantcontact, None)
    betrokkenen = expanded(openklant, str(klantcontact["url"]), "hadBetrokkenen")
    assert [b["uuid"] for b in betrokkenen] == [betrokkene["uuid"]]
    assert cast("dict[str, str]", betrokkenen[0]["contactnaam"])["achternaam"] == "test"
