"""Open Zaak test data through the ZGW APIs; every factory registers its deleter (PLAN.md §4 B)."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.steps import TEST_CATALOGUS_RSIN

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

ZAKEN = "zaken/api/v1"
CATALOGI = "catalogi/api/v1"


def today() -> str:
    """Today's date as the ZGW APIs expect it."""
    return datetime.now(tz=UTC).date().isoformat()


def _create(openzaak: ApiClient, registry: ResourceRegistry, path: str, body: dict[str, object]) -> JsonObject:
    created = openzaak.post(path, body)
    url = str(created["url"])
    registry.add(f"{path} {url}", lambda: openzaak.delete(url))
    return created


def make_zaak(openzaak: ApiClient, registry: ResourceRegistry, zaaktype: str, **fields: object) -> JsonObject:
    """A zaak of a zaaktype whose omschrijving carries the run tag; fields override the defaults."""
    body: dict[str, object] = {
        "bronorganisatie": TEST_CATALOGUS_RSIN,
        "verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN,
        "zaaktype": zaaktype,
        "startdatum": today(),
        "omschrijving": registry.tagged("zaak"),
        "vertrouwelijkheidaanduiding": "openbaar",
        **fields,
    }
    return _create(openzaak, registry, f"{ZAKEN}/zaken", body)
