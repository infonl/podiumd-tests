"""ZAC: zaken koppelen and ontkoppelen, and its search for zaken to link, as ZAC's REST API does it for the UI.

The zaken are of the estate's productaanvraag zaaktype (fixture zac_zaak), which allows no deelzaken: hoofdzaak and
deelzaak are refused here.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import NIET_ONTVANKELIJK
from podiumd_tests.zac import koppel
from podiumd_tests.zac import koppel_zoekresultaat
from podiumd_tests.zac import ontkoppel
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import wait_in_werkvoorraad

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, zaak-lifecycle).",
    ),
]

GERELATEERD = "GERELATEERD"


def _relaties(zac: requests.Session, zac_url: str, zaak: JsonObject) -> list[tuple[str, str]]:
    """The zaak's linked zaken as ZAC shows them: (identificatie, relatieType)."""
    gekoppeld = entries(read_zaak(zac, zac_url, str(zaak["uuid"])).get("gerelateerdeZaken"))
    return [(str(item.get("identificatie")), str(item.get("relatieType"))) for item in gekoppeld]


def _in_open_zaak(openzaak: ApiClient, openzaak_url: str, zaak: JsonObject) -> list[str]:
    """The URLs of the zaak's gerelateerdeZaken in Open Zaak."""
    found = openzaak.get(f"{openzaak_url}/{ZAKEN}/zaken/{zaak['uuid']}")
    return [str(item.get("url")) for item in entries(found.get("gerelateerdeZaken"))]


def _zaak_url(openzaak_url: str, zaak: JsonObject) -> str:
    return f"{openzaak_url}/{ZAKEN}/zaken/{zaak['uuid']}"


def _reden(zac: requests.Session, zac_url: str, zaak: JsonObject, ander: JsonObject, relatie: str) -> object:
    """Wait until ZAC's koppel search finds the other zaak; the reason it cannot be linked (None: it can)."""
    found = wait_until(
        lambda: koppel_zoekresultaat(zac, zac_url, zaak, ander, relatie),
        timeout=INDEX_TIMEOUT,
        description=f"zaak {ander['identificatie']} in the koppel search of {zaak['identificatie']}",
    )
    return found.get("nietKoppelbaarReden")


@pytest.mark.scenario("""
    Given two open zaken in ZAC
    When the behandelaar links them as gerelateerd
    Then each zaak shows the other as gerelateerd, in ZAC and in Open Zaak
    When the behandelaar unlinks them from the other zaak, with a reden
    Then neither zaak shows the other
""")
def test_gerelateerde_zaken_show_each_other_until_ontkoppeld(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
) -> None:
    """GERELATEERD shows on both zaken; ontkoppelen from the other zaak removes it from both."""
    zaak, ander = zac_zaak(), zac_zaak()
    expect_status(koppel(zac, urls["zac"], zaak, ander, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _relaties(zac, urls["zac"], zaak) == [(ander["identificatie"], GERELATEERD)]
    assert _relaties(zac, urls["zac"], ander) == [(zaak["identificatie"], GERELATEERD)]
    assert _in_open_zaak(openzaak_productaanvraag, urls["openzaak"], zaak) == [_zaak_url(urls["openzaak"], ander)]
    assert _in_open_zaak(openzaak_productaanvraag, urls["openzaak"], ander) == [_zaak_url(urls["openzaak"], zaak)]

    response = ontkoppel(zac, urls["zac"], ander, zaak, GERELATEERD, "podiumd-tests")
    expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _relaties(zac, urls["zac"], zaak) == []
    assert _relaties(zac, urls["zac"], ander) == []


@pytest.mark.scenario("""
    Given two open zaken in ZAC
    When the behandelaar searches for zaken to link to the first zaak
    Then the search does not offer the zaak itself
    And it offers the second zaak as gerelateerd
    When the zaken are linked
    Then the search marks the second zaak as already gerelateerd
    And linking it again is refused
""")
def test_koppel_search_leaves_out_the_zaak_and_marks_a_linked_one(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """The koppel search leaves out the zaak itself and gives ALREADY_GERELATEERD for a linked zaak."""
    zaak, ander = zac_zaak(), zac_zaak()
    wait_in_werkvoorraad(zac, urls["zac"], str(zaak["identificatie"]))
    assert koppel_zoekresultaat(zac, urls["zac"], zaak, zaak, GERELATEERD) is None
    assert _reden(zac, urls["zac"], zaak, ander, GERELATEERD) is None

    expect_status(koppel(zac, urls["zac"], zaak, ander, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _reden(zac, urls["zac"], zaak, ander, GERELATEERD) == "ALREADY_GERELATEERD"
    expect_status(koppel(zac, urls["zac"], zaak, ander, GERELATEERD), *REFUSED)


@pytest.mark.scenario("""
    Given an open zaak and a closed zaak in ZAC
    When the behandelaar searches from the open zaak
    Then the closed zaak can be gerelateerd but not become a deelzaak
    And linking it as gerelateerd is accepted, also from the closed zaak
""")
def test_closed_zaak_can_be_gerelateerd_but_not_deelzaak(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """A closed zaak: DEELZAAK gives AFGEHANDELD; GERELATEERD is accepted from the open and from the closed zaak."""
    zaak, gesloten = zac_zaak(), zac_zaak()
    afbreken = zac.patch(
        f"{urls['zac']}/rest/zaken/zaak/{gesloten['uuid']}/afbreken", json={"zaakbeeindigRedenId": NIET_ONTVANKELIJK}
    )
    expect_status(afbreken, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    wait_until(
        lambda: (
            (koppel_zoekresultaat(zac, urls["zac"], zaak, gesloten, "DEELZAAK") or {}).get("nietKoppelbaarReden")
            == "AFGEHANDELD"
        ),
        timeout=INDEX_TIMEOUT,
        description=f"zaak {gesloten['identificatie']} closed in the koppel search",
    )
    assert _reden(zac, urls["zac"], zaak, gesloten, GERELATEERD) is None

    expect_status(koppel(zac, urls["zac"], zaak, gesloten, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _relaties(zac, urls["zac"], zaak) == [(gesloten["identificatie"], GERELATEERD)]
    nog_een = zac_zaak()
    expect_status(koppel(zac, urls["zac"], gesloten, nog_een, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert (nog_een["identificatie"], GERELATEERD) in _relaties(zac, urls["zac"], gesloten)


@pytest.mark.parametrize("relatie", ["HOOFDZAAK", "DEELZAAK"])
@pytest.mark.scenario("""
    Given two open zaken of a zaaktype that allows no deelzaken
    When the behandelaar searches for a hoofdzaak or a deelzaak
    Then the search says the zaaktype allows no deelzaak
    And linking them that way is refused, and Open Zaak records no hoofdzaak
""")
def test_zaaktype_without_deelzaaktypen_refuses_hoofd_and_deelzaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
    relatie: str,
) -> None:
    """HOOFDZAAK and DEELZAAK give ZAAKTYPE_DOES_NOT_ALLOW_DEELZAAK and are refused."""
    zaak, ander = zac_zaak(), zac_zaak()
    zaaktype = section(read_zaak(zac, urls["zac"], str(zaak["uuid"])), "zaaktype")
    if any(item.get("relatieType") == "DEELZAAK" for item in entries(zaaktype.get("zaaktypeRelaties"))):
        pytest.skip(f"zaaktype {zaaktype.get('identificatie')} allows deelzaken")
    assert _reden(zac, urls["zac"], zaak, ander, relatie) == "ZAAKTYPE_DOES_NOT_ALLOW_DEELZAAK"
    expect_status(koppel(zac, urls["zac"], zaak, ander, relatie), *REFUSED)
    for each in (zaak, ander):
        assert openzaak_productaanvraag.get(_zaak_url(urls["openzaak"], each)).get("hoofdzaak") is None
