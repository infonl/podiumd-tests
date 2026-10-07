"""Chain: a klantcontact in Open Klant linked to a zaak in Open Zaak. Ported from TA regression 18."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import make_onderwerpobject
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openzaak", "openklant")]


@pytest.mark.core
def test_klantcontact_about_a_zaak_is_found_by_the_zaak(
    openklant: ApiClient, openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> None:
    """The KCC flow: a klantcontact linked to a zaak shows the link and is found by the zaak's uuid."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype)
    klantcontact = make_klantcontact(openklant, registry)
    link = make_onderwerpobject(openklant, registry, klantcontact, str(zaak["uuid"]))
    read = openklant.get(f"klantcontacten/{klantcontact['uuid']}")
    assert [o["uuid"] for o in entries(read["gingOverOnderwerpobjecten"])] == [link["uuid"]]
    found = openklant.list("onderwerpobjecten", {"onderwerpobjectidentificatorObjectId": str(zaak["uuid"])})
    assert [o["uuid"] for o in found] == [link["uuid"]]
