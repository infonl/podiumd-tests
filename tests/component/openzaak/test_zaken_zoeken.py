"""Open Zaak zaak search: list filters and _zoek find the zaak by its own fields and its rollen, and filter others out."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import after_period
from podiumd_tests.seed.openzaak import close_zaak
from podiumd_tests.seed.openzaak import make_rol
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("openzaak"),
    pytest.mark.source(
        "external OneGround/ZGW-APIs-postman-tests ZGW features, ZRC zaak zoekopties",
        "ZAC and Open Archiefbeheer find zaken by these filters; a filter that matches must find the zaak, one that "
        "does not must leave it out.",
    ),
]

STARTDATUM = "2025-03-04"
AFGEHANDELD = datetime(2025, 3, 20, 12, tzinfo=UTC)

type Case = tuple[dict[str, str], bool]


@pytest.fixture(name="gezocht")
def fixture_gezocht(openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts) -> JsonObject:
    """A zaak started on STARTDATUM and closed at AFGEHANDELD, with an initiator of a random BSN; "bsn" holds it."""
    zaak = make_zaak(openzaak, registry, parts.zaaktype, startdatum=STARTDATUM)
    bsn = random_bsn()
    make_rol(openzaak, registry, zaak, parts.roltypen["initiator"], inpBsn=bsn)
    return {**close_zaak(openzaak, zaak, parts, AFGEHANDELD), "bsn": bsn}


def _cases(zaak: JsonObject) -> list[Case]:
    """(filter, whether it matches the zaak); each is combined with the zaak's identificatie."""
    bsn = str(zaak["bsn"])
    einddatum = str(zaak["einddatum"])
    archiefactiedatum = str(zaak["archiefactiedatum"])
    return [
        ({"identificatie": str(zaak["identificatie"])}, True),
        ({"startdatum": STARTDATUM}, True),
        ({"startdatum__gt": STARTDATUM}, False),
        ({"startdatum__lte": STARTDATUM}, True),
        ({"einddatum": einddatum}, True),
        ({"einddatum__gt": einddatum}, False),
        ({"einddatum__lt": after_period(einddatum, "P1D")}, True),
        ({"einddatum__isnull": "true"}, False),
        ({"archiefactiedatum": archiefactiedatum}, True),
        ({"archiefactiedatum__lt": archiefactiedatum}, False),
        ({"archiefactiedatum__gt": einddatum}, True),
        ({"archiefactiedatum__isnull": "true"}, False),
        ({"rol__betrokkeneIdentificatie__natuurlijkPersoon__inpBsn": bsn}, True),
        ({"rol__betrokkeneIdentificatie__natuurlijkPersoon__inpBsn": random_bsn()}, False),
        ({"rol__omschrijvingGeneriek": "initiator"}, True),
        ({"rol__omschrijvingGeneriek": "behandelaar"}, False),
        ({"rol__betrokkeneType": "natuurlijk_persoon"}, True),
        ({"rol__betrokkeneType": "medewerker"}, False),
        ({"maximaleVertrouwelijkheidaanduiding": "openbaar"}, True),
        ({"archiefstatus": "gearchiveerd"}, False),
    ]


@pytest.mark.parametrize("search", ["list", "_zoek"])
@pytest.mark.scenario("""
    Given a closed zaak with a start date and a citizen as initiator
    When zaken are searched by identificatie, start, end or archive date, the citizen's BSN, rol and archive status
    Then each matching search finds the zaak
    And each non-matching search leaves it out
""")
def test_filters_find_and_leave_out_the_zaak(openzaak: ApiClient, gezocht: JsonObject, search: str) -> None:
    """Each filter, with the zaak's identificatie, finds the zaak when it matches and not otherwise."""
    wrong = []
    for query, matches in _cases(gezocht):
        params = {"identificatie": str(gezocht["identificatie"]), **query}
        if search == "list":
            found = openzaak.list(f"{ZAKEN}/zaken", params)
        else:
            found = entries(
                openzaak.request("POST", f"{ZAKEN}/zaken/_zoek", HTTPStatus.OK, json=params).json()["results"]
            )
        if (gezocht["url"] in [z["url"] for z in found]) != matches:
            wrong.append((query, matches))
    assert not wrong, f"(filter, should match) pairs Open Zaak answered wrongly: {wrong}"
