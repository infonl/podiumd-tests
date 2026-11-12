"""ZAC: zaken koppelen and ontkoppelen, and its search for zaken to link, as ZAC's REST API does it for the UI.

Gerelateerd and the refusals of the estate's productaanvraag zaaktype (fixture zac_zaak), which allows no deelzaken;
hoofdzaak and deelzaak with podiumd-tests' own zaaktype, its own deelzaaktype (fixture zac_eigen_zaak).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import DEELZAAK
from podiumd_tests.zac import GERELATEERD
from podiumd_tests.zac import HOOFDZAAK
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import afbreken
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import afsluiten
from podiumd_tests.zac import attribuut_historie
from podiumd_tests.zac import can_open_zaak
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import koppel
from podiumd_tests.zac import koppel_zoekresultaat
from podiumd_tests.zac import ontkoppel
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import wait_for_indicatie
from podiumd_tests.zac import wait_in_werkvoorraad

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

# The attribuut of Open Zaak's historie for a zaak's gerelateerde zaken.
GERELATEERDE_ZAKEN = "gerelateerdeZaken"
# The tests of fixture zac_eigen_zaaktype, a throwaway zaaktype made known to PABC and deleted with a Django snippet.
EIGEN_ZAAKTYPE = pytest.mark.xdist_group("zac-eigen-zaaktype")
THROWAWAY = pytest.mark.requires("pabc", "cluster")


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


def _wait_for_reden(
    zac: requests.Session, zac_url: str, zaak: JsonObject, ander: JsonObject, relatie: str, reden: str
) -> None:
    """Wait until ZAC's koppel search gives this reason for the other zaak: it reads the zaken from its index."""
    wait_until(
        lambda: (koppel_zoekresultaat(zac, zac_url, zaak, ander, relatie) or {}).get("nietKoppelbaarReden") == reden,
        timeout=INDEX_TIMEOUT,
        description=f"{reden} for zaak {ander['identificatie']} in the koppel search of {zaak['identificatie']}",
    )


@pytest.mark.scenario("""
    Given two open zaken in ZAC
    When the behandelaar links them as gerelateerd
    Then each zaak shows the other as gerelateerd, in ZAC and in Open Zaak
    And the first zaak's historie records the link
    When the behandelaar unlinks them from the other zaak, with a reden
    Then neither zaak shows the other
    And the other zaak's historie records the unlink with the reden
""")
def test_gerelateerde_zaken_show_each_other_until_ontkoppeld(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
) -> None:
    """GERELATEERD shows on both zaken; ontkoppelen from the other zaak removes it from both; both are in the historie."""
    zaak, ander = zac_zaak(), zac_zaak()
    expect_status(koppel(zac, urls["zac"], zaak, ander, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _relaties(zac, urls["zac"], zaak) == [(ander["identificatie"], GERELATEERD)]
    assert _relaties(zac, urls["zac"], ander) == [(zaak["identificatie"], GERELATEERD)]
    assert _in_open_zaak(openzaak_productaanvraag, urls["openzaak"], zaak) == [_zaak_url(urls["openzaak"], ander)]
    assert _in_open_zaak(openzaak_productaanvraag, urls["openzaak"], ander) == [_zaak_url(urls["openzaak"], zaak)]

    assert (None, ander["identificatie"], "") in attribuut_historie(zac, urls["zac"], zaak, GERELATEERDE_ZAKEN)

    response = ontkoppel(zac, urls["zac"], ander, zaak, GERELATEERD, "podiumd-tests")
    expect_status(response, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _relaties(zac, urls["zac"], zaak) == []
    assert _relaties(zac, urls["zac"], ander) == []
    assert (zaak["identificatie"], None, "podiumd-tests") in attribuut_historie(
        zac, urls["zac"], ander, GERELATEERDE_ZAKEN
    )


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
    wait_in_werkvoorraad(zac, urls["zac"], zaak)
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
    expect_status(afbreken(zac, urls["zac"], gesloten), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    _wait_for_reden(zac, urls["zac"], zaak, gesloten, DEELZAAK, "AFGEHANDELD")
    assert _reden(zac, urls["zac"], zaak, gesloten, GERELATEERD) is None

    expect_status(koppel(zac, urls["zac"], zaak, gesloten, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _relaties(zac, urls["zac"], zaak) == [(gesloten["identificatie"], GERELATEERD)]
    nog_een = zac_zaak()
    expect_status(koppel(zac, urls["zac"], gesloten, nog_een, GERELATEERD), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert (nog_een["identificatie"], GERELATEERD) in _relaties(zac, urls["zac"], gesloten)


@pytest.mark.parametrize("relatie", [HOOFDZAAK, DEELZAAK])
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
    if any(item.get("relatieType") == DEELZAAK for item in entries(zaaktype.get("zaaktypeRelaties"))):
        pytest.skip(f"zaaktype {zaaktype.get('identificatie')} allows deelzaken")
    assert _reden(zac, urls["zac"], zaak, ander, relatie) == "ZAAKTYPE_DOES_NOT_ALLOW_DEELZAAK"
    expect_status(koppel(zac, urls["zac"], zaak, ander, relatie), *REFUSED)
    for each in (zaak, ander):
        assert openzaak_productaanvraag.get(_zaak_url(urls["openzaak"], each)).get("hoofdzaak") is None


def _is_closed(zac: requests.Session, zac_url: str, zaak: JsonObject) -> bool:
    return read_zaak(zac, zac_url, str(zaak["uuid"]))["isOpen"] is False


def _linked(
    zac: requests.Session, zac_url: str, hoofd: JsonObject, deel: JsonObject, vanaf: str, reden: str | None = None
) -> requests.Response:
    """Link (without reden) or unlink the deelzaak, from the hoofdzaak or from the deelzaak; ZAC's answer."""
    zaak, ander, relatie = (hoofd, deel, DEELZAAK) if vanaf == "hoofdzaak" else (deel, hoofd, HOOFDZAAK)
    if reden is None:
        return koppel(zac, zac_url, zaak, ander, relatie)
    return ontkoppel(zac, zac_url, zaak, ander, relatie, reden)


@EIGEN_ZAAKTYPE
@THROWAWAY
@pytest.mark.parametrize("vanaf", ["hoofdzaak", "deelzaak"])
@pytest.mark.scenario("""
    Given two open zaken of a zaaktype that allows itself as deelzaaktype
    When the behandelaar links the second as deelzaak of the first, from either zaak
    Then the first shows the second as deelzaak and the second the first as hoofdzaak
    And Open Zaak records the first as hoofdzaak of the second
    And ZAC marks them hoofdzaak and deelzaak, also in the werkvoorraad
""")
def test_hoofd_and_deelzaak_show_on_both_zaken(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaak: Callable[[], JsonObject],
    openzaak: ApiClient,
    vanaf: str,
) -> None:
    """DEELZAAK from the hoofdzaak and HOOFDZAAK from the deelzaak link the same way, in ZAC and Open Zaak."""
    hoofd, deel = zac_eigen_zaak(), zac_eigen_zaak()
    expect_status(_linked(zac, urls["zac"], hoofd, deel, vanaf), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _relaties(zac, urls["zac"], hoofd) == [(deel["identificatie"], DEELZAAK)]
    assert _relaties(zac, urls["zac"], deel) == [(hoofd["identificatie"], HOOFDZAAK)]
    assert openzaak.get(_zaak_url(urls["openzaak"], deel)).get("hoofdzaak") == _zaak_url(urls["openzaak"], hoofd)
    assert HOOFDZAAK in strings(read_zaak(zac, urls["zac"], str(hoofd["uuid"])).get("indicaties"))
    assert DEELZAAK in strings(read_zaak(zac, urls["zac"], str(deel["uuid"])).get("indicaties"))
    wait_for_indicatie(zac, urls["zac"], hoofd, HOOFDZAAK)
    wait_for_indicatie(zac, urls["zac"], deel, DEELZAAK)


@EIGEN_ZAAKTYPE
@THROWAWAY
@pytest.mark.parametrize("beeindigen", [afhandelen, afbreken], ids=["afhandelen", "afbreken"])
@pytest.mark.scenario("""
    Given a hoofdzaak in behandeling with an open deelzaak
    When the behandelaar afhandelt or afbreekt the hoofdzaak
    Then it is refused and the hoofdzaak stays open
    When the deelzaak is ontkoppeld with a reden
    Then the hoofdzaak can be afgehandeld or afgebroken
""")
def test_hoofdzaak_is_afgehandeld_once_its_open_deelzaak_is_ontkoppeld(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaak: Callable[[], JsonObject],
    beeindigen: Callable[[requests.Session, str, JsonObject], requests.Response],
) -> None:
    """Afhandelen or afbreken of a hoofdzaak with an open deelzaak is refused; after ontkoppelen it is accepted."""
    hoofd, deel = zac_eigen_zaak(), zac_eigen_zaak()
    expect_status(_linked(zac, urls["zac"], hoofd, deel, "hoofdzaak"), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    afronden_intake(zac, urls["zac"], hoofd)
    expect_status(beeindigen(zac, urls["zac"], hoofd), HTTPStatus.BAD_REQUEST)
    assert not _is_closed(zac, urls["zac"], hoofd)

    unlinked = _linked(zac, urls["zac"], hoofd, deel, "hoofdzaak", "podiumd-tests")
    expect_status(unlinked, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    expect_status(beeindigen(zac, urls["zac"], hoofd), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _is_closed(zac, urls["zac"], hoofd)


@EIGEN_ZAAKTYPE
@THROWAWAY
@pytest.mark.parametrize("vanaf", ["hoofdzaak", "deelzaak"])
@pytest.mark.scenario("""
    Given a hoofdzaak in behandeling with a deelzaak
    When the deelzaak is closed
    Then ontkoppelen is refused while the hoofdzaak is open
    And the hoofdzaak can be afgehandeld
    When both are closed, the behandelaar unlinks them from either zaak with a reden
    Then neither zaak shows the other
""")
def test_closed_deelzaak_is_ontkoppeld_once_the_hoofdzaak_is_closed(
    zac: requests.Session, urls: dict[str, str], zac_eigen_zaak: Callable[[], JsonObject], vanaf: str
) -> None:
    """A closed deelzaak lets the hoofdzaak be afgehandeld; ZAC unlinks hoofd- and deelzaak only when both are open or
    both are closed.
    """
    hoofd, deel = zac_eigen_zaak(), zac_eigen_zaak()
    expect_status(_linked(zac, urls["zac"], hoofd, deel, vanaf), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    afronden_intake(zac, urls["zac"], hoofd)
    expect_status(afbreken(zac, urls["zac"], deel), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    expect_status(_linked(zac, urls["zac"], hoofd, deel, vanaf, "podiumd-tests"), *REFUSED)

    expect_status(afhandelen(zac, urls["zac"], hoofd), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _is_closed(zac, urls["zac"], hoofd)
    unlinked = _linked(zac, urls["zac"], hoofd, deel, vanaf, "podiumd-tests")
    expect_status(unlinked, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _relaties(zac, urls["zac"], hoofd) == []
    assert _relaties(zac, urls["zac"], deel) == []


@EIGEN_ZAAKTYPE
@THROWAWAY
@pytest.mark.parametrize(
    ("van", "naar", "reden"),
    [("deel", "derde", "IS_DEELZAAK"), ("derde", "deel", "ALREADY_DEELZAAK"), ("derde", "hoofd", "HAS_DEELZAKEN")],
)
@pytest.mark.scenario("""
    Given a hoofdzaak with a deelzaak, and a third open zaak, of a zaaktype that allows itself as deelzaaktype
    When the behandelaar searches for a deelzaak of the deelzaak, or for the deelzaak or hoofdzaak from the third zaak
    Then the search says the zaak is a deelzaak, is already a deelzaak, or has deelzaken
    And linking them that way is refused
""")
def test_deelzaak_cannot_become_deel_or_hoofdzaak_again(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaak: Callable[[], JsonObject],
    van: str,
    naar: str,
    reden: str,
) -> None:
    """The koppel search for a DEELZAAK gives IS_DEELZAAK, ALREADY_DEELZAAK or HAS_DEELZAKEN; koppelen is refused."""
    zaken = {"hoofd": zac_eigen_zaak(), "deel": zac_eigen_zaak(), "derde": zac_eigen_zaak()}
    linked = _linked(zac, urls["zac"], zaken["hoofd"], zaken["deel"], "hoofdzaak")
    expect_status(linked, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    _wait_for_reden(zac, urls["zac"], zaken[van], zaken[naar], DEELZAAK, reden)
    expect_status(koppel(zac, urls["zac"], zaken[van], zaken[naar], DEELZAAK), *REFUSED)


@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given a zaak of the BPMN test zaaktype, and a zaak of a zaaktype outside the behandelaar's domain
    When a behandelaar of the BPMN test zaaktype links the second zaak to the first as gerelateerd
    Then ZAC refuses it
    And the first zaak shows no gerelateerde zaak
""")
def test_zaak_the_user_may_not_read_is_not_gerelateerd(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_zaak: Callable[..., JsonObject],
) -> None:
    """GERELATEERD to a zaak the behandelaar cannot open answers 401 or 403."""
    onleesbaar = zac_zaak()
    behandelaar = zac_as("behandelaar")
    assert not can_open_zaak(behandelaar, urls["zac"], onleesbaar)
    expect_status(koppel(behandelaar, urls["zac"], bpmn_zaak, onleesbaar, GERELATEERD), *REFUSED)
    assert _relaties(zac, urls["zac"], bpmn_zaak) == []


@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given two afgehandelde zaken of the BPMN test zaaktype
    When a behandelaar links them as gerelateerd
    Then ZAC refuses it
    When a recordmanager links them as gerelateerd
    Then each zaak shows the other as gerelateerd
""")
def test_closed_zaken_are_gerelateerd_by_a_recordmanager_only(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    openzaak: ApiClient,
    bpmn_zaak: JsonObject,
    bpmn_parameters: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """GERELATEERD between two closed zaken: 401 or 403 for the behandelaar, accepted for the recordmanager."""
    ander = create_zaak(zac, urls["zac"], bpmn_parameters, omschrijving=registry.tagged("bpmn"))
    clean_up_zaak(zac, urls["zac"], openzaak, registry, ander)
    for zaak in (bpmn_zaak, ander):
        expect_status(afsluiten(zac, urls["zac"], zaak), HTTPStatus.OK)
    expect_status(koppel(zac_as("behandelaar"), urls["zac"], bpmn_zaak, ander, GERELATEERD), *REFUSED)
    assert _relaties(zac, urls["zac"], bpmn_zaak) == []

    linked = koppel(zac_as("recordmanager"), urls["zac"], bpmn_zaak, ander, GERELATEERD)
    expect_status(linked, HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert _relaties(zac, urls["zac"], bpmn_zaak) == [(ander["identificatie"], GERELATEERD)]
    assert _relaties(zac, urls["zac"], ander) == [(bpmn_zaak["identificatie"], GERELATEERD)]
