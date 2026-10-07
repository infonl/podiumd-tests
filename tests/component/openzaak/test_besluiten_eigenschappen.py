"""Open Zaak besluiten and zaakeigenschappen on the test zaaktype.

Ported from TA regression 24 and 29; unlike TA, the besluittype and eigenschap come from
bootstrap, so no test publishes a type it cannot delete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openzaak import BESLUITEN
from podiumd_tests.seed.openzaak import make_besluit
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


def test_besluit_on_a_zaak(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A besluit of the zaak's besluittype reads back and is found by besluittype and zaak (TA reg-29)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    besluit = make_besluit(openzaak, registry, parts.besluittype, zaak=zaak["url"])
    read = openzaak.get(str(besluit["url"]))
    assert (read["besluittype"], read["zaak"], read["toelichting"]) == (
        parts.besluittype,
        zaak["url"],
        registry.tagged("besluit"),
    )
    assert [b["url"] for b in openzaak.list(f"{BESLUITEN}/besluiten", {"zaak": str(zaak["url"])})] == [besluit["url"]]


def test_zaakeigenschap(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A value for eigenschap kenteken is stored on the zaak (TA reg-24)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    url = f"{zaak['url']}/zaakeigenschappen"
    created = openzaak.post(
        url, {"zaak": zaak["url"], "eigenschap": parts.eigenschappen["kenteken"], "waarde": "12-AB-34"}
    )
    assert (created["naam"], created["waarde"]) == ("kenteken", "12-AB-34")
    listed = openzaak.list(url)
    assert [e["waarde"] for e in listed] == ["12-AB-34"]
