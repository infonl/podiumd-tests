"""Open Klant partijen: create, read, update, filter and delete through the API."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.seed.openklant import make_partij

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openklant")]


def test_partij_lifecycle(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """A created partij reads back, accepts a PATCH and is gone after DELETE."""
    partij = make_partij(openklant, registry)
    url = str(partij["url"])
    assert openklant.get(url)["soortPartij"] == "persoon"
    assert openklant.patch(url, {"indicatieActief": False})["indicatieActief"] is False
    openklant.delete(url)
    openklant.request("GET", url, 404)


def test_partij_is_found_by_its_nummer(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """The nummer Open Klant assigns is a working filter."""
    partij = make_partij(openklant, registry)
    found = openklant.list("partijen", {"nummer": str(partij["nummer"])})
    assert [p["url"] for p in found] == [partij["url"]]


def test_contactnaam_is_stored(openklant: ApiClient, registry: ResourceRegistry) -> None:
    """The partij identification comes back as sent."""
    partij = make_partij(openklant, registry)
    identificatie = cast("dict[str, dict[str, str]]", openklant.get(str(partij["url"]))["partijIdentificatie"])
    assert identificatie["contactnaam"]["achternaam"] == registry.tagged("partij")
