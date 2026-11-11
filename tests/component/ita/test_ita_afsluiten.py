"""ITA as the klantcontactmedewerker: closing a contactverzoek, and the historie lists.

Ported from ITA's own Playwright suite (InterneTaakAfhandeling.EndToEndTest), as the API calls of its pages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ITA_GROEP
from podiumd_tests.ita import afdeling_or_groep_historie
from podiumd_tests.ita import answer_body
from podiumd_tests.ita import assign_to_me
from podiumd_tests.ita import close_with_klantcontact
from podiumd_tests.ita import make_contactverzoek
from podiumd_tests.ita import my_afdelingen_and_groepen
from podiumd_tests.ita import my_internetaken
from podiumd_tests.ita import uuids
from podiumd_tests.seed.openklant import clean_up_klantcontacten
from podiumd_tests.seed.openklant import close_internetaak
from podiumd_tests.seed.openklant import klantcontact_body
from podiumd_tests.seed.openklant import klantcontacten_about
from podiumd_tests.seed.openklant import make_actor

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("ita", "openklant", "objecten", "keycloak")]

SCENARIOS = "upstream interne-taak-afhandeling/ITA InterneTaakAfhandeling.EndToEndTest/Contactverzoek/ContactverzoekScenarios.cs"


def close_contactverzoek(
    ita: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry, taak: JsonObject
) -> str:
    """Close the internetaak in ITA with a contactmoment that succeeded; the contactmoment's onderwerp."""
    onderwerp = registry.tagged(f"afsluiten-{taak['nummer']}")
    clean_up_klantcontacten(openklant, registry, onderwerp)
    contactmoment = klantcontact_body(registry, onderwerp=onderwerp, indicatieContactGelukt=True)
    close_with_klantcontact(ita, urls["ita"], answer_body(taak, contactmoment))
    return onderwerp


@pytest.mark.source(SCENARIOS, "Opslaan en afsluiten sets the contactverzoek verwerkt, with afgehandeldOp.")
@pytest.mark.source(SCENARIOS, "An unassigned contactverzoek, assigned to oneself and closed, is in Mijn historie.")
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And an unassigned contactverzoek in Open Klant
    When the medewerker assigns it to themselves
    And closes it with a contactmoment that succeeded
    Then the contactverzoek is verwerkt in Open Klant, with the moment it was afgehandeld
    And the contactmoment is in Open Klant, marked gelukt
    And the contactverzoek left the medewerker's open list for Mijn historie
""")
def test_closing_a_contactverzoek_moves_it_to_mijn_historie(
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    internetaak: JsonObject,
) -> None:
    """Closing with a klantcontact sets the internetaak verwerkt with afgehandeldOp; ITA lists it in Mijn historie."""
    assign_to_me(ita, urls["ita"], internetaak)
    assert internetaak["uuid"] in uuids(my_internetaken(ita, urls["ita"]))
    onderwerp = close_contactverzoek(ita, urls, openklant, registry, internetaak)
    closed = openklant.get(f"internetaken/{internetaak['uuid']}")
    assert (closed["status"], bool(closed.get("afgehandeldOp"))) == ("verwerkt", True), closed
    assert [k["indicatieContactGelukt"] for k in klantcontacten_about(openklant, onderwerp)] == [True]
    assert internetaak["uuid"] not in uuids(my_internetaken(ita, urls["ita"]))
    assert internetaak["uuid"] in uuids(my_internetaken(ita, urls["ita"], afgerond=True))


# Intermittent: 1 in 259 full runs; a parallel test's cleanup deletes its klantcontacten while ITA builds the list.
@pytest.mark.xfail(
    strict=False,
    reason="[ita-4] ITA 3.3.4 answers 500 for Mijn historie when a listed contactverzoek is deleted before it fetches "
    "its klantcontact; not yet reported upstream",
)
@pytest.mark.source(SCENARIOS, "Mijn historie lists the contactverzoek assigned and closed last on top.")
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And two contactverzoeken the medewerker assigned to themselves one after the other
    When the medewerker closes both in the same order
    Then Mijn historie lists the second above the first
""")
def test_mijn_historie_lists_the_latest_first(
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    logboek_type: str,
) -> None:
    """Mijn historie orders the closed contactverzoeken newest first (ITA sorts on toegewezenOp)."""
    taken = [make_contactverzoek(openklant, objecten, registry, logboek_type) for _ in range(2)]
    for taak in taken:
        assign_to_me(ita, urls["ita"], taak)
    for taak in taken:
        close_contactverzoek(ita, urls, openklant, registry, taak)
    ours = uuids(taken)
    historie = [uuid for uuid in uuids(my_internetaken(ita, urls["ita"], afgerond=True)) if uuid in ours]
    assert historie == list(reversed(ours))


@pytest.mark.parametrize(("soort", "objecttype"), [("afdeling", "afd"), ("groep", "grp")])
@pytest.mark.source(SCENARIOS, "Afdelings- and Groephistorie list the closed contactverzoeken of an afdeling or groep.")
@pytest.mark.scenario("""
    Given the KCC medewerker is logged in to ITA
    And an open and a closed contactverzoek of an afdeling or groep
    When the medewerker opens the Afdelings- or Groephistorie of it
    Then ITA lists the closed contactverzoek and not the open one
    And lists the open one among the afdeling's or groep's open contactverzoeken
""")
def test_afdelings_and_groepshistorie_list_the_closed_contactverzoeken(
    ita: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    objecten: ApiClient,
    registry: ResourceRegistry,
    logboek_type: str,
    soort: str,
    objecttype: str,
) -> None:
    """ITA's afdelingen-groepen overview lists an afdeling's or groep's verwerkt internetaken, or its open ones."""
    naam = registry.tagged(soort)
    actor = make_actor(openklant, registry, "organisatorische_eenheid", naam, objecttype)
    taken = [make_contactverzoek(openklant, objecten, registry, logboek_type, [actor]) for _ in range(2)]
    open_taak, closed_taak = uuids(taken)
    close_internetaak(openklant, taken[1])
    assert uuids(afdeling_or_groep_historie(ita, urls["ita"], naam)) == [closed_taak]
    assert uuids(afdeling_or_groep_historie(ita, urls["ita"], naam, afgerond=False)) == [open_taak]


@pytest.mark.source(SCENARIOS, "The Afdelingshistorie offers the medewerker's own afdelingen and groepen to choose.")
@pytest.mark.scenario("""
    Given the KCC medewerker is a member of a groep in the Objecten register
    When the medewerker opens the Afdelingshistorie in ITA
    Then ITA offers that groep to choose
""")
def test_afdelingshistorie_offers_the_medewerkers_groepen(
    ita: requests.Session, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """ITA's gebruiker-groepen-and-afdelingen names the groep of the KCC user's Medewerker object."""
    need_bootstrap("objecten-medewerker-kcc")
    assert ITA_GROEP in my_afdelingen_and_groepen(ita, urls["ita"])
