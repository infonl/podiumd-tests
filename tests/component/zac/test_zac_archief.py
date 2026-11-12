"""ZAC: the archiving of a closed zaak: the brondatum per afleidingswijze, the besluit it needs, set afterwards.

The zaken are of a throwaway zaaktype with a resultaattype per brondatum afleidingswijze, a besluittype with publicatie
and a zaakbeeindigreden (fixture zac_archief_zaak); the second users are bootstrap's test users of one ZAC role.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.catalogi import ARCHIEF_PROCESTERMIJN
from podiumd_tests.seed.openzaak import BESLUITEN
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import after_period
from podiumd_tests.zac import DEELZAAK
from podiumd_tests.zac import afbreken
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import afsluiten
from podiumd_tests.zac import besluittypen
from podiumd_tests.zac import brondatum_zetten
from podiumd_tests.zac import heropenen
from podiumd_tests.zac import koppel
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import recorded_besluit
from podiumd_tests.zac import resultaattypen
from podiumd_tests.zac import vastleggen_besluit
from podiumd_tests.zac import zoned_brondatum

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "keycloak", "pabc", "cluster"),
    # Fixture zac_archief_zaaktype: one throwaway zaaktype per run, made known to PABC.
    pytest.mark.xdist_group("zac-archief-zaaktype"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
    ),
]

# Days from today of the dates the tests give: a brondatum, a besluit's ingangsdatum and its vervaldatum.
BRONDATUM_DAYS = 5
INGANGSDATUM_DAYS = 2
VERVALDATUM_DAYS = 30


def _day(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()  # noqa: DTZ011  # ZAC's local date


def _resultaattype(zac: requests.Session, zac_url: str, zaak: JsonObject, afleidingswijze: str) -> str:
    """The id of the zaaktype's resultaattype named after its afleidingswijze."""
    return next(str(item["id"]) for item in resultaattypen(zac, zac_url, zaak) if item.get("naam") == afleidingswijze)


def _in_open_zaak(openzaak: ApiClient, zaak: JsonObject) -> JsonObject:
    return openzaak.get(f"{ZAKEN}/zaken/{zaak['uuid']}")


def _archiefactiedatum(openzaak: ApiClient, closed: JsonObject, brondatum: str) -> str:
    """The archiefactiedatum Open Zaak derives from the brondatum: the resultaattype's archiefactietermijn after it."""
    resultaat = openzaak.get(str(closed["resultaat"]))
    termijn = openzaak.get(str(resultaat["resultaattype"]))["archiefactietermijn"]
    return after_period(brondatum, str(termijn))


@pytest.fixture(name="in_behandeling")
def fixture_in_behandeling(
    zac: requests.Session, urls: dict[str, str], zac_archief_zaak: Callable[[], JsonObject]
) -> Callable[[], JsonObject]:
    """Start a zaak of the archief zaaktype and finish its intake as ontvankelijk."""

    def start() -> JsonObject:
        zaak = zac_archief_zaak()
        afronden_intake(zac, urls["zac"], zaak)
        return zaak

    return start


def _afgehandeld_zonder_brondatum(
    zac: requests.Session, zac_url: str, openzaak: ApiClient, in_behandeling: Callable[[], JsonObject]
) -> tuple[JsonObject, str]:
    """A zaak afgehandeld with the eigenschap resultaat without brondatum, and that resultaattype's id."""
    zaak = in_behandeling()
    resultaattype = _resultaattype(zac, zac_url, zaak, "eigenschap")
    expect_status(afhandelen(zac, zac_url, zaak, resultaattype), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _in_open_zaak(openzaak, zaak)["startdatumBewaartermijn"] is None
    return zaak, resultaattype


@pytest.fixture(name="besluit")
def fixture_besluit(
    zac: requests.Session, urls: dict[str, str], openzaak: ApiClient, registry: ResourceRegistry
) -> Callable[..., JsonObject]:
    """Record a besluit of the archief zaaktype's besluittype on a zaak; cleanup deletes it before the zaak."""

    def record(zaak: JsonObject, **fields: object) -> JsonObject:
        besluittype = besluittypen(zac, urls["zac"], zaak)[0]
        return recorded_besluit(zac, urls["zac"], openzaak, registry, zaak, besluittype, **fields)

    return record


@pytest.mark.parametrize(
    ("afleidingswijze", "besluit_days"),
    [
        pytest.param("eigenschap", {}, id="eigenschap"),
        pytest.param("termijn", {}, id="termijn"),
        pytest.param("ingangsdatum_besluit", {"ingangsdatum": INGANGSDATUM_DAYS}, id="ingangsdatum-besluit"),
        pytest.param(
            "vervaldatum_besluit",
            {"ingangsdatum": INGANGSDATUM_DAYS, "vervaldatum": VERVALDATUM_DAYS},
            id="vervaldatum-besluit",
        ),
    ],
)
@pytest.mark.scenario("""
    Given a zaak in behandeling of a zaaktype with a resultaat per brondatum afleidingswijze
    When the behandelaar afhandelt it with the resultaat of one afleidingswijze, with a brondatum or a besluit it needs
    Then Open Zaak's brondatum is that brondatum, the einddatum plus the procestermijn, or the besluit's date
    And the archiefactiedatum is the archiefactietermijn after the brondatum
""")
def test_brondatum_follows_the_afleidingswijze_of_the_resultaat(  # the fixtures and parameters
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    in_behandeling: Callable[[], JsonObject],
    besluit: Callable[..., JsonObject],
    afleidingswijze: str,
    besluit_days: dict[str, int],
) -> None:
    """startdatumBewaartermijn per afleidingswijze; archiefactiedatum the archiefactietermijn after it."""
    zaak = in_behandeling()
    if besluit_days:
        besluit(zaak, **{field: _day(days) for field, days in besluit_days.items()})
    fields = {"brondatum": zoned_brondatum(_day(BRONDATUM_DAYS))} if afleidingswijze == "eigenschap" else {}
    resultaattype = _resultaattype(zac, urls["zac"], zaak, afleidingswijze)
    expect_status(afhandelen(zac, urls["zac"], zaak, resultaattype, **fields), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    closed = _in_open_zaak(openzaak, zaak)
    expected = {
        "eigenschap": _day(BRONDATUM_DAYS),
        "termijn": after_period(str(closed["einddatum"]), ARCHIEF_PROCESTERMIJN),
        "ingangsdatum_besluit": _day(INGANGSDATUM_DAYS),
        "vervaldatum_besluit": _day(VERVALDATUM_DAYS),
    }[afleidingswijze]
    assert closed["startdatumBewaartermijn"] == expected
    assert closed["archiefactiedatum"] == _archiefactiedatum(openzaak, closed, expected)


@pytest.mark.xfail(
    strict=True,
    reason="[open-zaak-14] Open Zaak 1.29.3 gives a deelzaak the hoofdzaak's brondatum, not its einddatum, for "
    "afleidingswijze hoofdzaak (by design since open-zaak#2072, against the ZGW definition); not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a hoofdzaak in behandeling with a deelzaak in behandeling
    When the behandelaar afhandelt the deelzaak with a resultaat that takes its brondatum from the hoofdzaak
    Then the deelzaak has no brondatum yet
    When the behandelaar afhandelt the hoofdzaak
    Then the deelzaak's brondatum is the hoofdzaak's einddatum
    And the deelzaak's archiefactiedatum is its archiefactietermijn after that
""")
def test_deelzaak_takes_its_brondatum_from_the_hoofdzaak(
    zac: requests.Session, urls: dict[str, str], openzaak: ApiClient, in_behandeling: Callable[[], JsonObject]
) -> None:
    """Afleidingswijze hoofdzaak: Open Zaak sets the deelzaak's startdatumBewaartermijn when the hoofdzaak closes.

    Open Zaak closes a hoofdzaak only after its deelzaken.
    """
    zac_url = urls["zac"]
    hoofd, deel = in_behandeling(), in_behandeling()
    expect_status(koppel(zac, zac_url, hoofd, deel, DEELZAAK), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    resultaattype = _resultaattype(zac, zac_url, deel, "hoofdzaak")
    expect_status(afhandelen(zac, zac_url, deel, resultaattype), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _in_open_zaak(openzaak, deel)["startdatumBewaartermijn"] is None
    resultaattype = _resultaattype(zac, zac_url, hoofd, "termijn")
    expect_status(afhandelen(zac, zac_url, hoofd, resultaattype), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    einddatum = str(_in_open_zaak(openzaak, hoofd)["einddatum"])
    closed = _in_open_zaak(openzaak, deel)
    assert closed["startdatumBewaartermijn"] == einddatum
    assert closed["archiefactiedatum"] == _archiefactiedatum(openzaak, closed, einddatum)


@pytest.mark.scenario("""
    Given a zaak in behandeling whose resultaat takes its brondatum from an eigenschap
    When the behandelaar afhandelt it with a brondatum before today
    Then ZAC refuses it and the zaak stays open
""")
def test_eigenschap_brondatum_before_the_afronddatum_is_refused(
    zac: requests.Session, urls: dict[str, str], in_behandeling: Callable[[], JsonObject]
) -> None:
    """ZAAK_AFHANDELEN with a brondatum of yesterday answers 400."""
    zaak = in_behandeling()
    resultaattype = _resultaattype(zac, urls["zac"], zaak, "eigenschap")
    refused = afhandelen(zac, urls["zac"], zaak, resultaattype, brondatum=zoned_brondatum(_day(-1)))
    assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is True


@pytest.mark.scenario("""
    Given a zaak in behandeling whose resultaat takes its brondatum from the ingangsdatum of a besluit
    When the behandelaar afhandelt it without a besluit
    Then it is refused and the zaak stays open
    When the behandelaar records a besluit and afhandelt it again
    Then the zaak is closed
""")
def test_resultaat_that_needs_a_besluit_waits_for_one(
    zac: requests.Session,
    urls: dict[str, str],
    in_behandeling: Callable[[], JsonObject],
    besluit: Callable[..., JsonObject],
) -> None:
    """ZAC marks the resultaattype besluitVerplicht; Open Zaak refuses the eindstatus with 400 until a besluit exists."""
    zaak = in_behandeling()
    resultaattype = _resultaattype(zac, urls["zac"], zaak, "ingangsdatum_besluit")
    offered = next(item for item in resultaattypen(zac, urls["zac"], zaak) if item["id"] == resultaattype)
    assert offered.get("besluitVerplicht") is True
    expect_status(afhandelen(zac, urls["zac"], zaak, resultaattype), HTTPStatus.BAD_REQUEST)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is True
    besluit(zaak)
    expect_status(afhandelen(zac, urls["zac"], zaak, resultaattype), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is False


@pytest.mark.scenario("""
    Given a zaak afgehandeld with a resultaat whose brondatum comes from an eigenschap, without a brondatum
    When a behandelaar sets the brondatum
    Then ZAC refuses it
    When a recordmanager sets a brondatum before the einddatum
    Then ZAC refuses it
    When the recordmanager sets a later brondatum
    Then Open Zaak has that brondatum and the archiefactiedatum after it, and the zaak keeps its resultaat
    And the recordmanager cannot set it a second time
""")
def test_recordmanager_sets_the_brondatum_of_a_closed_zaak(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    openzaak: ApiClient,
    in_behandeling: Callable[[], JsonObject],
) -> None:
    """BRONDATUM_ZETTEN: 403 for the behandelaar, 400 before the einddatum, once for the recordmanager."""
    zac_url = urls["zac"]
    zaak, resultaattype = _afgehandeld_zonder_brondatum(zac, zac_url, openzaak, in_behandeling)
    expect_status(brondatum_zetten(zac_as("behandelaar"), zac_url, zaak, _day(3)), *REFUSED)
    recordmanager = zac_as("recordmanager")
    expect_status(brondatum_zetten(recordmanager, zac_url, zaak, _day(-1)), HTTPStatus.BAD_REQUEST)

    expect_status(brondatum_zetten(recordmanager, zac_url, zaak, _day(3)), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    closed = _in_open_zaak(openzaak, zaak)
    assert closed["startdatumBewaartermijn"] == _day(3)
    assert closed["archiefactiedatum"] == _archiefactiedatum(openzaak, closed, _day(3))
    shown = section(section(read_zaak(zac, zac_url, str(zaak["uuid"])), "resultaat"), "resultaattype")
    assert shown.get("id") == resultaattype
    expect_status(brondatum_zetten(recordmanager, zac_url, zaak, _day(4)), *REFUSED)


@pytest.mark.xfail(
    strict=True,
    reason="[zac-32] ZAC 5.9.1 refuses a new brondatum after heropenen (403): heropenen keeps the eigenschap, so "
    "Open Zaak derives the old brondatum again and policy brondatum_zetten forbids a second one; not yet reported "
    "upstream",
)
@pytest.mark.scenario("""
    Given a zaak afgehandeld with a resultaat whose brondatum comes from an eigenschap, and a brondatum set
    When a recordmanager heropent it and it is afgehandeld again with that resultaat
    Then the recordmanager can set a new brondatum
""")
def test_recordmanager_sets_the_brondatum_again_after_heropenen(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    openzaak: ApiClient,
    in_behandeling: Callable[[], JsonObject],
) -> None:
    """After heropenen and afsluiten BRONDATUM_ZETTEN is accepted again and gives the new brondatum."""
    zac_url = urls["zac"]
    zaak, resultaattype = _afgehandeld_zonder_brondatum(zac, zac_url, openzaak, in_behandeling)
    recordmanager = zac_as("recordmanager")
    expect_status(brondatum_zetten(recordmanager, zac_url, zaak, _day(3)), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    expect_status(heropenen(recordmanager, zac_url, zaak), HTTPStatus.OK)
    expect_status(afsluiten(zac, zac_url, zaak, resultaattype), HTTPStatus.OK)
    response = brondatum_zetten(recordmanager, zac_url, zaak, _day(4))
    assert response.status_code in {HTTPStatus.OK, HTTPStatus.NO_CONTENT}, describe(response)
    assert _in_open_zaak(openzaak, zaak)["startdatumBewaartermijn"] == _day(4)


@pytest.mark.scenario("""
    Given a zaak in behandeling of a zaaktype whose besluittype has publicatie, with a reactietermijn of 14 days
    When the behandelaar records a besluit with a publicatiedatum but no uiterlijke reactiedatum
    Then ZAC refuses it
    When the uiterlijke reactiedatum is before the publicatiedatum plus the reactietermijn
    Then ZAC refuses it
    When the behandelaar records it with a publicatiedatum and the uiterlijke reactiedatum 14 days later
    Then Open Zaak has the besluit with both dates
""")
def test_besluit_publicatie_dates_follow_the_besluittype(
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    in_behandeling: Callable[[], JsonObject],
    besluit: Callable[..., JsonObject],
) -> None:
    """publicationDate needs lastResponseDate, at least the reactietermijn later; both are stored in Open Zaak."""
    zaak = in_behandeling()
    besluittype = besluittypen(zac, urls["zac"], zaak)[0]
    termijn = int(str(section(besluittype, "publication")["responseTermDays"]))
    publicatie = {"ingangsdatum": _day(0), "publicationDate": _day(1)}
    for reactie in ({}, {"lastResponseDate": _day(1 + termijn - 1)}):
        refused = vastleggen_besluit(zac, urls["zac"], zaak, besluittype, **publicatie, **reactie)
        assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    created = besluit(zaak, **publicatie, lastResponseDate=_day(1 + termijn))
    stored = openzaak.get(f"{BESLUITEN}/besluiten/{created['uuid']}")
    assert (stored["publicatiedatum"], stored["uiterlijkeReactiedatum"]) == (_day(1), _day(1 + termijn))


@pytest.mark.scenario("""
    Given a zaak of a zaaktype with a zaakbeeindigreden in its zaakafhandelparameters
    When the behandelaar breaks the zaak off
    Then ZAC offers that reden besides niet ontvankelijk
    When the behandelaar breaks it off with that reden
    Then the zaak is closed with the resultaat of that reden and the reden as toelichting of its status
""")
def test_afbreken_with_a_zaakbeeindigreden_of_the_zaakafhandelparameters(
    zac: requests.Session,
    urls: dict[str, str],
    zac_archief_zaaktype: JsonObject,
    zac_archief_zaak: Callable[[], JsonObject],
) -> None:
    """The zaaktype's zaakbeeindigredenen list it; afbreken with its id gives its resultaattype and its naam."""
    parameter = entries(zac_archief_zaaktype.get("zaakbeeindigParameters"))[0]
    reden, resultaattype = section(parameter, "zaakbeeindigReden"), section(parameter, "resultaattype")
    uuid = section(zac_archief_zaaktype, "zaaktype")["uuid"]
    offered = get_entries(zac, f"{urls['zac']}/rest/zaakafhandelparameters/zaakbeeindigredenen/{uuid}")
    assert str(reden["id"]) in {str(item.get("id")) for item in offered}
    zaak = zac_archief_zaak()
    closed = expect_status(afbreken(zac, urls["zac"], zaak, str(reden["id"])), HTTPStatus.OK).json()
    assert closed["isOpen"] is False
    assert section(section(closed, "resultaat"), "resultaattype").get("id") == resultaattype["id"]
    assert section(closed, "status").get("toelichting") == reden["naam"]
