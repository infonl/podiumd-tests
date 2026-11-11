"""Open Zaak archiefnominatie and archiefactiedatum of a closed zaak, per brondatum afleidingswijze of its resultaattype.

The archief zaaktype's resultaattypen are named after their afleidingswijze and all have an archiefactietermijn of
3650 days, so every archiefactiedatum lies years ahead and no destruction list of Open Archiefbeheer picks it up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_besluit
from podiumd_tests.seed.openzaak import make_status
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("openzaak"),
    pytest.mark.source(
        "external OneGround/ZGW-APIs-postman-tests ZGW business rule zrc-021",
        "Closing a zaak derives archiefnominatie and archiefactiedatum from the resultaattype's afleidingswijze.",
    ),
]

ARCHIEFACTIETERMIJN = timedelta(days=3650)
PEILDATUM = "peildatum"


@dataclass(frozen=True)
class Archief:
    """The archief zaaktype's types and its resultaattypen by afleidingswijze."""

    parts: ZaaktypeParts
    resultaattypen: dict[str, str]


@dataclass(frozen=True)
class Given:
    """A zaak of the archief zaaktype, and what its brondatum may be taken from."""

    openzaak: ApiClient
    registry: ResourceRegistry
    archief: Archief
    zaak: JsonObject


@pytest.fixture(scope="module", name="archief")
def fixture_archief(openzaak: ApiClient, archief_parts: ZaaktypeParts) -> Archief:
    """Return the archief zaaktype's types and its resultaattypen by afleidingswijze."""
    resultaattypen = {
        str(r["omschrijving"]): str(r["url"])
        for r in openzaak.list(f"{CATALOGI}/resultaattypen", {"zaaktype": archief_parts.zaaktype})
    }
    if not resultaattypen:
        pytest.skip("archief zaaktype has no resultaattypen (Selectielijst API was unreachable at bootstrap)")
    return Archief(archief_parts, resultaattypen)


def _close(
    openzaak: ApiClient, zaak: JsonObject, archief: Archief, afleidingswijze: str, gezet: datetime
) -> JsonObject:
    body = {"zaak": zaak["url"], "resultaattype": archief.resultaattypen[afleidingswijze]}
    openzaak.post(f"{ZAKEN}/resultaten", body)
    make_status(openzaak, zaak, str(archief.parts.statustypen[-1]["url"]), "Afgehandeld", gezet)
    return openzaak.get(str(zaak["url"]))


def _days_ago(days: int) -> datetime:
    return datetime.now(tz=UTC).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=days)


def _brondatum_afgehandeld(_: Given) -> date:
    return _days_ago(2).date()


def _brondatum_eigenschap(given: Given) -> date:
    peildatum = date(2026, 1, 15)
    eigenschap = given.archief.parts.eigenschappen[PEILDATUM]
    body = {"zaak": given.zaak["url"], "eigenschap": eigenschap, "waarde": f"{peildatum}T00:00:00Z"}
    given.openzaak.post(f"{given.zaak['url']}/zaakeigenschappen", body)
    return peildatum


def _besluit(given: Given) -> JsonObject:
    besluittype = given.archief.parts.besluittype
    dates = {"ingangsdatum": "2026-02-01", "vervaldatum": "2026-03-01"}
    return make_besluit(given.openzaak, given.registry, besluittype, zaak=given.zaak["url"], **dates)


def _brondatum_ingangsdatum_besluit(given: Given) -> date:
    return date.fromisoformat(str(_besluit(given)["ingangsdatum"]))


def _brondatum_vervaldatum_besluit(given: Given) -> date:
    return date.fromisoformat(str(_besluit(given)["vervaldatum"]))


@pytest.mark.parametrize(
    ("afleidingswijze", "brondatum_of"),
    [
        ("afgehandeld", _brondatum_afgehandeld),
        ("eigenschap", _brondatum_eigenschap),
        ("ingangsdatum_besluit", _brondatum_ingangsdatum_besluit),
        ("vervaldatum_besluit", _brondatum_vervaldatum_besluit),
    ],
)
@pytest.mark.scenario("""
    Given a zaak whose resultaat dates its archiving from the zaak's end, a date eigenschap or a besluit
    When the zaak is closed
    Then its archiefnominatie is the resultaattype's
    And its archiefactiedatum is that brondatum plus the archiefactietermijn
""")
def test_archiefactiedatum_follows_the_afleidingswijze(
    openzaak: ApiClient,
    registry: ResourceRegistry,
    archief: Archief,
    afleidingswijze: str,
    brondatum_of: Callable[[Given], date],
) -> None:
    """archiefactiedatum is the brondatum of the resultaattype's afleidingswijze plus 3650 days."""
    zaak = make_zaak(openzaak, registry, archief.parts.zaaktype)
    brondatum = brondatum_of(Given(openzaak, registry, archief, zaak))
    closed = _close(openzaak, zaak, archief, afleidingswijze, _days_ago(2))
    assert closed["archiefnominatie"] == "vernietigen"
    assert closed["archiefactiedatum"] == (brondatum + ARCHIEFACTIETERMIJN).isoformat()


@pytest.mark.scenario("""
    Given a zaak whose resultaat has a brondatum to be determined by hand
    When the zaak is closed
    Then its archiefnominatie is the resultaattype's
    And it has no archiefactiedatum
""")
def test_ander_datumkenmerk_leaves_the_archiefactiedatum_open(
    openzaak: ApiClient, registry: ResourceRegistry, archief: Archief
) -> None:
    """With afleidingswijze ander_datumkenmerk closing sets archiefnominatie and no archiefactiedatum."""
    zaak = make_zaak(openzaak, registry, archief.parts.zaaktype)
    closed = _close(openzaak, zaak, archief, "ander_datumkenmerk", _days_ago(2))
    assert (closed["archiefnominatie"], closed["archiefactiedatum"]) == ("vernietigen", None)


@pytest.mark.scenario("""
    Given a deelzaak whose resultaat dates its archiving from its hoofdzaak
    When the deelzaak is closed
    Then it has no archiefactiedatum yet
    When the hoofdzaak is closed
    Then the deelzaak's archiefactiedatum is the hoofdzaak's einddatum plus the archiefactietermijn
""")
def test_deelzaak_takes_its_archiefactiedatum_from_the_hoofdzaak(
    openzaak: ApiClient, registry: ResourceRegistry, archief: Archief
) -> None:
    """A deelzaak of afleidingswijze hoofdzaak gets its archive fields when the hoofdzaak closes, not when it does."""
    hoofdzaak = make_zaak(openzaak, registry, archief.parts.zaaktype)
    deelzaak = make_zaak(openzaak, registry, archief.parts.zaaktype, hoofdzaak=hoofdzaak["url"])
    closed = _close(openzaak, deelzaak, archief, "hoofdzaak", _days_ago(3))
    assert closed["archiefactiedatum"] is None
    einddatum = date.fromisoformat(str(_close(openzaak, hoofdzaak, archief, "afgehandeld", _days_ago(1))["einddatum"]))
    deelzaak = openzaak.get(str(deelzaak["url"]))
    assert deelzaak["archiefnominatie"] == "vernietigen"
    assert deelzaak["archiefactiedatum"] == (einddatum + ARCHIEFACTIETERMIJN).isoformat()
