"""Open Notificaties test data; every factory registers its deleter (PLAN.md §4 B)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# What Open Notificaties sends as Authorization to the callback; the receiver records it.
CALLBACK_AUTH = "Bearer ptest-callback"


def abonnement_body(callback_url: str, kanaal: str, filters: dict[str, str]) -> dict[str, object]:
    """An abonnement on one kanaal."""
    return {"callbackUrl": callback_url, "auth": CALLBACK_AUTH, "kanalen": [{"naam": kanaal, "filters": filters}]}


def make_abonnement(
    opennotificaties: ApiClient, registry: ResourceRegistry, callback_url: str, kanaal: str, filters: dict[str, str]
) -> JsonObject:
    """An abonnement on one kanaal, sending to callback_url."""
    created = opennotificaties.post("abonnement", abonnement_body(callback_url, kanaal, filters))
    url = str(created["url"])
    registry.add(f"abonnement {url}", lambda: opennotificaties.delete(url))
    return created
