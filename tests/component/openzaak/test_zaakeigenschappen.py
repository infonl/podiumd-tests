"""Open Zaak zaakeigenschappen on the test zaaktype.

Ported from TA regression 24; the eigenschap comes from bootstrap, so no test publishes a type it cannot delete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import zaakeigenschap_body

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


@pytest.mark.source(
    "TA regression/24-zaakeigenschappen.spec.ts",
    "Open Formulieren passes form fields to a zaak as zaakeigenschappen, which ZAC and the portal show.",
)
@pytest.mark.scenario("""
    Given a zaak in Open Zaak
    When the value 12-AB-34 is stored for the zaaktype's eigenschap kenteken
    Then the zaakeigenschap has the name kenteken and that value
    And the zaak's zaakeigenschappen hold only that value
""")
def test_zaakeigenschap(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> None:
    """A value for eigenschap kenteken is stored on the zaak (TA reg-24)."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    url = f"{zaak['url']}/zaakeigenschappen"
    created = openzaak.post(url, zaakeigenschap_body(zaak, parts))
    assert (created["naam"], created["waarde"]) == ("kenteken", "12-AB-34")
    listed = openzaak.list(url)
    assert [e["waarde"] for e in listed] == ["12-AB-34"]
