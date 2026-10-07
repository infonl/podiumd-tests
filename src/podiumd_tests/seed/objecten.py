"""Objecten test data; every factory registers its deleter (PLAN.md §4 B)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


def make_productaanvraag(
    objecten: ApiClient, registry: ResourceRegistry, objecttype: str, productaanvraagtype: str, kenmerk: str
) -> JsonObject:
    """A productaanvraag object as Open Formulieren's objects API registration writes it."""
    body: dict[str, object] = {
        "type": objecttype,
        "record": {
            "typeVersion": 1,
            "data": {
                "bron": {"naam": "Open Formulieren", "kenmerk": kenmerk},
                "type": productaanvraagtype,
                "aanvraaggegevens": {"melding": {"naamAanvrager": "podiumd-tests", "omschrijving": kenmerk}},
                "taal": "nld",
            },
            "startAt": today(),
        },
    }
    created = objecten.post("objects", body)
    url = str(created["url"])
    registry.add(f"object {url}", lambda: objecten.delete(url))
    return created
