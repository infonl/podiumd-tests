"""Open Klant klantcontacten: CRUD, filters, actors and betrokkenen.

Ported from TA interaction 09 and regression 86, 87 and 149.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_betrokkene
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import ref

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openklant")]


@pytest.mark.core
def test_klantcontact_roundtrip(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """A klantcontact reads back with its fields and a nummer (TA int-09, reg-87)."""
    created = make_klantcontact(openklant, registry, kanaal="balie")
    read = openklant.get(str(created["url"]))
    assert (read["kanaal"], read["onderwerp"], read["indicatieContactGelukt"]) == ("balie", created["onderwerp"], True)
    assert read["nummer"]


def test_klantcontact_patch_and_delete(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """A PATCH changes onderwerp and inhoud; after DELETE the klantcontact is gone (TA reg-149)."""
    url = str(make_klantcontact(openklant, registry)["url"])
    changed = openklant.patch(url, {"onderwerp": registry.tagged("gewijzigd"), "inhoud": "gewijzigd"})
    assert (changed["onderwerp"], changed["inhoud"]) == (registry.tagged("gewijzigd"), "gewijzigd")
    openklant.delete(url)
    openklant.request("GET", url, 404)


def test_klantcontacten_list_and_filter_on_kanaal(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """The list is paginated, and the kanaal filter finds a new klantcontact (TA reg-87)."""
    page = openklant.get("klantcontacten", {"pageSize": "5"})
    assert isinstance(page["results"], list)
    assert isinstance(page["count"], int)
    created = make_klantcontact(openklant, registry, kanaal="balie")
    found = {
        str(k["uuid"])
        for k in openklant.list("klantcontacten", {"kanaal": "balie", "onderwerp": str(created["onderwerp"])})
    }
    assert str(created["uuid"]) in found


def test_actor_linked_to_klantcontact(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """A medewerker linked through actorklantcontacten shows in hadBetrokkenActoren (TA int-09)."""
    actor = make_actor(openklant, registry)
    klantcontact = make_klantcontact(openklant, registry)
    link = openklant.post("actorklantcontacten", {"klantcontact": ref(klantcontact), "actor": ref(actor)})
    registry.add("actorklantcontact", lambda: openklant.delete(str(link["url"])))
    actors = entries(openklant.get(str(klantcontact["url"]))["hadBetrokkenActoren"])
    assert [a["uuid"] for a in actors] == [actor["uuid"]]


def test_expand_had_betrokkenen(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """expand=hadBetrokkenen inlines an anonymous betrokkene (TA reg-87)."""
    klantcontact = make_klantcontact(openklant, registry)
    betrokkene = make_betrokkene(openklant, registry, klantcontact, None)
    read = openklant.get(str(klantcontact["url"]), {"expand": "hadBetrokkenen"})
    expanded = entries(section(read, "_expand").get("hadBetrokkenen"))
    assert [b["uuid"] for b in expanded] == [betrokkene["uuid"]]
    assert cast("dict[str, str]", expanded[0]["contactnaam"])["achternaam"] == "test"
