"""ZAC: besluiten on a zaak, as ZAC's REST API records, changes and withdraws them for the UI.

The besluittype is bootstrap's (step openzaak-zac-besluittype) on the estate's productaanvraag zaaktype; a besluit is
deleted before its zaak, which Open Zaak keeps otherwise.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap import names
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import BESLUITEN
from podiumd_tests.zac import HEROPEND
from podiumd_tests.zac import afbreken
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import besluittypen
from podiumd_tests.zac import heropenen
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import recorded_besluit
from podiumd_tests.zac import vastleggen_besluit
from podiumd_tests.zac_documents import uploaded_document

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
    ),
]

BESLUITTYPE = f"{names.PREFIX}-zac-besluit"


@pytest.fixture(name="besluittype")
def fixture_besluittype(
    zac: requests.Session,
    urls: dict[str, str],
    need_bootstrap: Callable[..., None],
) -> Callable[[JsonObject], JsonObject]:
    """Return the bootstrap besluittype as ZAC offers it for a zaak; skips when ZAC does not offer it."""
    need_bootstrap("openzaak-zac-besluittype")

    def of(zaak: JsonObject) -> JsonObject:
        found = [item for item in besluittypen(zac, urls["zac"], zaak) if item.get("naam") == BESLUITTYPE]
        if not found:
            pytest.skip(f"ZAC offers no besluittype {BESLUITTYPE}: allow it with profile setting zac_besluittype")
        return found[0]

    return of


@pytest.fixture(name="in_behandeling")
def fixture_in_behandeling(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> Callable[[], JsonObject]:
    """Start a zaak in ZAC and finish its intake as ontvankelijk: a besluit can be recorded from In behandeling."""

    def start() -> JsonObject:
        zaak = zac_zaak()
        afronden_intake(zac, urls["zac"], zaak)
        return zaak

    return start


@pytest.fixture(name="besluit")
def fixture_besluit(
    zac: requests.Session,
    urls: dict[str, str],
    besluittype: Callable[[JsonObject], JsonObject],
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
) -> Callable[..., JsonObject]:
    """Record a besluit on a zaak in ZAC, valid from today; cleanup deletes it before the zaak."""

    def record(zaak: JsonObject, **fields: object) -> JsonObject:
        return recorded_besluit(zac, urls["zac"], openzaak_productaanvraag, registry, zaak, besluittype(zaak), **fields)

    return record


def _besluiten(zac: requests.Session, zac_url: str, zaak: JsonObject) -> list[JsonObject]:
    return entries(
        expect_status(zac.get(f"{zac_url}/rest/zaken/besluit/zaakUuid/{zaak['uuid']}"), HTTPStatus.OK).json()
    )


def _afhandelen(zac: requests.Session, zac_url: str, zaak: JsonObject) -> None:
    expect_status(afhandelen(zac, zac_url, zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)


@pytest.mark.scenario("""
    Given a new zaak in ZAC, in the intake
    When the behandelaar records a besluit
    Then ZAC refuses it
    When the intake is finished as ontvankelijk and the behandelaar records a besluit
    Then the zaak lists the besluit, and Open Zaak has it on the zaak
""")
def test_besluit_is_recorded_after_the_intake_only(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    besluittype: Callable[[JsonObject], JsonObject],
    besluit: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
) -> None:
    """A besluit is refused during the intake, accepted In behandeling, and stored in Open Zaak on the zaak."""
    zaak = zac_zaak()
    today = date.today().isoformat()  # noqa: DTZ011  # ZAC's local date
    refused = vastleggen_besluit(zac, urls["zac"], zaak, besluittype(zaak), ingangsdatum=today)
    expect_status(refused, *REFUSED)

    afronden_intake(zac, urls["zac"], zaak)
    created = besluit(zaak)
    assert [item["uuid"] for item in _besluiten(zac, urls["zac"], zaak)] == [created["uuid"]]
    stored = openzaak_productaanvraag.get(f"{urls['openzaak']}/{BESLUITEN}/besluiten/{created['uuid']}")
    assert str(stored["zaak"]).endswith(f"/zaken/{zaak['uuid']}")


@pytest.mark.scenario("""
    Given a zaak in behandeling in ZAC
    When the behandelaar records a besluit without ingangsdatum
    Then ZAC refuses it
""")
def test_besluit_without_ingangsdatum_is_refused(
    zac: requests.Session,
    urls: dict[str, str],
    in_behandeling: Callable[[], JsonObject],
    besluittype: Callable[[JsonObject], JsonObject],
) -> None:
    """A besluit without ingangsdatum answers 400."""
    zaak = in_behandeling()
    response = vastleggen_besluit(zac, urls["zac"], zaak, besluittype(zaak), toelichting="podiumd-tests")
    expect_status(response, HTTPStatus.BAD_REQUEST)
    assert _besluiten(zac, urls["zac"], zaak) == []


@pytest.mark.scenario("""
    Given a zaak in behandeling whose besluittype has no publicatie
    When the behandelaar records a besluit with a publicatiedatum and an uiterlijke reactiedatum
    Then ZAC refuses it
""")
def test_besluit_without_publicatie_refuses_publicatie_dates(
    zac: requests.Session,
    urls: dict[str, str],
    in_behandeling: Callable[[], JsonObject],
    besluittype: Callable[[JsonObject], JsonObject],
) -> None:
    """publicationDate and lastResponseDate answer 400 for a besluittype with publicatieIndicatie false."""
    zaak = in_behandeling()
    gekozen = besluittype(zaak)
    if section(gekozen, "publication").get("enabled"):
        pytest.skip(f"besluittype {BESLUITTYPE} has publicatie")
    today = date.today().isoformat()  # noqa: DTZ011  # ZAC's local date
    dates = {"ingangsdatum": today, "publicationDate": today, "lastResponseDate": today}
    refused = vastleggen_besluit(zac, urls["zac"], zaak, gekozen, **dates)
    assert refused.status_code == HTTPStatus.BAD_REQUEST, describe(refused)
    assert _besluiten(zac, urls["zac"], zaak) == []


@pytest.mark.scenario("""
    Given a besluit with a vervaldatum on a zaak in behandeling
    When the behandelaar changes it without the vervaldatum, with a reden
    Then Open Zaak's besluit has no vervaldatum
""")
def test_cleared_vervaldatum_stays_cleared(
    zac: requests.Session,
    urls: dict[str, str],
    in_behandeling: Callable[[], JsonObject],
    besluit: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
) -> None:
    """PUT besluit without vervaldatum clears it in Open Zaak."""
    zaak = in_behandeling()
    later = (date.today() + timedelta(days=30)).isoformat()  # noqa: DTZ011  # ZAC's local date
    created = besluit(zaak, vervaldatum=later)
    change = {"besluitUuid": created["uuid"], "ingangsdatum": created["ingangsdatum"], "reden": "podiumd-tests"}
    expect_status(zac.put(f"{urls['zac']}/rest/zaken/besluit", json=change), HTTPStatus.OK)
    stored = openzaak_productaanvraag.get(f"{urls['openzaak']}/{BESLUITEN}/besluiten/{created['uuid']}")
    assert stored["vervaldatum"] is None


@pytest.mark.scenario("""
    Given a besluit on a zaak in behandeling
    When the behandelaar changes its toelichting without a reden
    Then ZAC refuses it
    When the behandelaar changes it with a reden
    Then the besluit has the new toelichting
    And the besluit's historie shows the change with the old value, the new value and the reden
""")
def test_besluit_wijzigen_needs_a_reden_and_is_in_the_historie(
    zac: requests.Session,
    urls: dict[str, str],
    in_behandeling: Callable[[], JsonObject],
    besluit: Callable[..., JsonObject],
) -> None:
    """PUT besluit needs a reden; the change and its reden are in the besluit's historie."""
    zaak = in_behandeling()
    created = besluit(zaak, toelichting="eerst")
    change = {"besluitUuid": created["uuid"], "ingangsdatum": created["ingangsdatum"], "toelichting": "daarna"}
    expect_status(zac.put(f"{urls['zac']}/rest/zaken/besluit", json=change), HTTPStatus.BAD_REQUEST)

    changed = zac.put(f"{urls['zac']}/rest/zaken/besluit", json={**change, "reden": "podiumd-tests wijziging"})
    assert expect_status(changed, HTTPStatus.OK).json()["toelichting"] == "daarna"
    historie = expect_status(zac.get(f"{urls['zac']}/rest/zaken/besluit/{created['uuid']}/historie"), HTTPStatus.OK)
    gewijzigd = [line for line in entries(historie.json()) if line.get("actie") == "GEWIJZIGD"]
    assert [(line.get("oudeWaarde"), line.get("nieuweWaarde"), line.get("toelichting")) for line in gewijzigd] == [
        ("eerst", "daarna", "podiumd-tests wijziging")
    ]


@pytest.mark.scenario("""
    Given a besluit on a zaak in behandeling
    When the behandelaar withdraws it without a reden
    Then ZAC refuses it
    When the behandelaar withdraws it with a reden, on behalf of the overheid
    Then ZAC shows the besluit as ingetrokken
    And Open Zaak has its vervaldatum and vervalreden
""")
def test_besluit_intrekken_needs_a_reden(
    zac: requests.Session,
    urls: dict[str, str],
    in_behandeling: Callable[[], JsonObject],
    besluit: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
) -> None:
    """Intrekken needs a reden and sets vervaldatum and vervalreden ingetrokken_overheid."""
    zaak = in_behandeling()
    created = besluit(zaak)
    today = date.today().isoformat()  # noqa: DTZ011  # ZAC's local date
    body = {"besluitUuid": created["uuid"], "vervaldatum": today, "vervalreden": "ingetrokken_overheid"}
    intrekken = f"{urls['zac']}/rest/zaken/besluit/intrekken"
    expect_status(zac.put(intrekken, json={**body, "reden": ""}), HTTPStatus.BAD_REQUEST)

    withdrawn = expect_status(zac.put(intrekken, json={**body, "reden": "podiumd-tests"}), HTTPStatus.OK).json()
    assert withdrawn["isIngetrokken"] is True
    stored = openzaak_productaanvraag.get(f"{urls['openzaak']}/{BESLUITEN}/besluiten/{created['uuid']}")
    assert (stored["vervaldatum"], stored["vervalreden"]) == (today, "ingetrokken_overheid")


@pytest.mark.scenario("""
    Given a besluit on a zaak in behandeling
    When the behandelaar afhandelt the zaak and a recordmanager heropent it
    Then the zaak is Heropend and still lists the besluit
    And the behandelaar can record another besluit
""")
def test_zaak_with_a_besluit_is_afgehandeld_and_heropend(
    zac: requests.Session,
    urls: dict[str, str],
    in_behandeling: Callable[[], JsonObject],
    besluit: Callable[..., JsonObject],
) -> None:
    """A zaak with a besluit can be afgehandeld and heropend; in Heropend a besluit can be recorded."""
    zaak = in_behandeling()
    eerste = besluit(zaak)
    _afhandelen(zac, urls["zac"], zaak)
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is False
    expect_status(heropenen(zac, urls["zac"], zaak), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert section(read_zaak(zac, urls["zac"], str(zaak["uuid"])), "status").get("naam") == HEROPEND

    tweede = besluit(zaak)
    assert {item["uuid"] for item in _besluiten(zac, urls["zac"], zaak)} == {eerste["uuid"], tweede["uuid"]}


@pytest.mark.scenario("""
    Given a zaak in behandeling with a document
    When the behandelaar records a besluit with that document
    Then the besluit lists the document
""")
def test_besluit_links_a_document_of_the_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    in_behandeling: Callable[[], JsonObject],
    besluit: Callable[..., JsonObject],
    registry: ResourceRegistry,
) -> None:
    """A besluit recorded with informatieobjecten lists that document."""
    zaak = in_behandeling()
    document = uploaded_document(zac, urls["zac"], zaak, registry)
    created = besluit(zaak, informatieobjecten=[document["uuid"]])
    listed = next(item for item in _besluiten(zac, urls["zac"], zaak) if item["uuid"] == created["uuid"])
    assert [item.get("uuid") for item in entries(listed.get("informatieobjecten"))] == [document["uuid"]]


@pytest.mark.xfail(
    strict=True,
    reason="[zac-10] ZAC 5.9.1 afbreekt a zaak with a besluit: its guard checks zaak.resultaat, not the besluiten; "
    "not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a besluit on a zaak in behandeling
    When the behandelaar breaks the zaak off
    Then ZAC refuses it, and the zaak stays open
""")
def test_zaak_with_a_besluit_cannot_be_afgebroken(
    zac: requests.Session,
    urls: dict[str, str],
    in_behandeling: Callable[[], JsonObject],
    besluit: Callable[..., JsonObject],
) -> None:
    """Afbreken of a zaak with a besluit is refused."""
    zaak = in_behandeling()
    besluit(zaak)
    afgebroken = afbreken(zac, urls["zac"], zaak)
    assert afgebroken.status_code >= HTTPStatus.BAD_REQUEST, f"afbreken answered {afgebroken.status_code}"
    assert read_zaak(zac, urls["zac"], str(zaak["uuid"]))["isOpen"] is True
