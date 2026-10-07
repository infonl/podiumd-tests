"""Open Zaak validation of a new zaak: each invalid field is named in invalidParams.

Ported from TA regression 44; unlike TA, every body is valid except for the field under test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("openzaak")]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("omschrijving", "x" * 200),
        ("vertrouwelijkheidaanduiding", "ultra-geheim"),
        ("zaaktype", "http://openzaak.invalid/catalogi/api/v1/zaaktypen/00000000-0000-0000-0000-000000000000"),
        ("bronorganisatie", None),
        ("bronorganisatie", "12345"),
        ("startdatum", "tomorrow"),
    ],
    ids=[
        "omschrijving-too-long",
        "unknown-vertrouwelijkheid",
        "unknown-zaaktype",
        "no-bronorganisatie",
        "short-rsin",
        "bad-date",
    ],
)
def test_invalid_zaak_names_the_field(
    openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts, field: str, value: object
) -> None:
    """POST /zaken with one invalid field answers 400 and names that field."""
    body: dict[str, object] = {
        "bronorganisatie": "000000000",
        "verantwoordelijkeOrganisatie": "000000000",
        "zaaktype": parts.zaaktype,
        "startdatum": today(),
        "omschrijving": registry.tagged("zaak"),
    }
    if value is None:
        del body[field]
    else:
        body[field] = value
    response = openzaak.request("POST", f"{ZAKEN}/zaken", 400, json=body)
    assert field in {str(p["name"]) for p in entries(response.json()["invalidParams"])}
