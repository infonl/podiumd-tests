"""Objecten test data; every factory registers its deleter (PLAN.md §4 B)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


def objecttype_url(env: Environment, name: str) -> str:
    """The URL Objecten knows an objecttype by (a registered ObjectType); LookupError when it has none."""
    found = cast(
        "dict[str, str | None]",
        run_snippet(env.kube, env.deployment_for("objecten"), "objecten_objecttype", {"name": name}),
    )
    if not found["url"]:
        msg = f"Objecten has no objecttype {name}"
        raise LookupError(msg)
    return found["url"]


def make_object(
    objecten: ApiClient, registry: ResourceRegistry, objecttype: str, data: dict[str, object]
) -> JsonObject:
    """An object of an objecttype (its URL as Objecten knows it), version 1, starting today."""
    body: dict[str, object] = {"type": objecttype, "record": {"typeVersion": 1, "data": data, "startAt": today()}}
    created = objecten.post("objects", body)
    url = str(created["url"])
    registry.add(f"object {url}", lambda: objecten.delete(url))
    return created


def make_productaanvraag(
    objecten: ApiClient, registry: ResourceRegistry, objecttype: str, productaanvraagtype: str, kenmerk: str
) -> JsonObject:
    """A productaanvraag object as Open Formulieren's objects API registration writes it."""
    data: dict[str, object] = {
        "bron": {"naam": "Open Formulieren", "kenmerk": kenmerk},
        "type": productaanvraagtype,
        "aanvraaggegevens": {"melding": {"naamAanvrager": "podiumd-tests", "omschrijving": kenmerk}},
        "taal": "nld",
    }
    return make_object(objecten, registry, objecttype, data)
