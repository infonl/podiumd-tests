"""Open Zaak zaken: create, read, update and delete through the Zaken API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


@pytest.mark.core
def test_zaak_lifecycle(openzaak: ApiClient, registry: ResourceRegistry, test_zaaktype: JsonObject) -> None:
    """A zaak reads back with an identificatie, accepts a PATCH and is gone after DELETE."""
    zaak = make_zaak(openzaak, registry, str(test_zaaktype["url"]))
    url = str(zaak["url"])
    read = openzaak.get(url)
    assert (read["zaaktype"], read["omschrijving"]) == (test_zaaktype["url"], registry.tagged("zaak"))
    assert read["identificatie"]
    assert openzaak.patch(url, {"toelichting": "podiumd-tests"})["toelichting"] == "podiumd-tests"
    openzaak.delete(url)
    openzaak.request("GET", url, 404)
