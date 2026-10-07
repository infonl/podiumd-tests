"""Open Klant test data; every factory registers its deleter (PLAN.md §4 B)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


def make_partij(openklant: ApiClient, registry: ResourceRegistry, **fields: object) -> JsonObject:
    """A persoon-partij named after the run tag; fields override the defaults."""
    body: dict[str, object] = {
        "soortPartij": "persoon",
        "indicatieActief": True,
        "indicatieGeheimhouding": False,
        "voorkeurstaal": "nld",
        "partijIdentificatie": {"contactnaam": {"voornaam": "PodiumD", "achternaam": registry.tagged("partij")}},
        "digitaleAdressen": [],
        "rekeningnummers": [],
        "voorkeursDigitaalAdres": None,
        "voorkeursRekeningnummer": None,
        **fields,
    }
    partij = openklant.post("partijen", body)
    url = str(partij["url"])
    registry.add(f"partij {url}", lambda: openklant.delete(url))
    return partij
