"""Open VTB: a verzoektype round trip through its API with the suite's own token."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openvtb", "cluster")]


@pytest.mark.core
def test_verzoektype_roundtrip(openvtb_verzoeken: ApiClient, registry: ResourceRegistry) -> None:
    """A verzoektype created with a token reads back by url and is gone after DELETE (204)."""
    naam = registry.tagged("verzoektype")
    created = openvtb_verzoeken.post("verzoektypen", {"naam": naam})
    url = str(created["url"])
    registry.add(f"openvtb verzoektype {naam}", lambda: openvtb_verzoeken.delete(url))
    assert openvtb_verzoeken.get(url)["naam"] == naam
    openvtb_verzoeken.delete(url)
    openvtb_verzoeken.request("GET", url, 404)
