"""ZAC's persons and companies: BRP and KvK lookups, betrokkenen and initiator of a zaak, e-mail from Open Klant.

The lookups are ported from TA regression 193. No estate routes ZAC to Open Zaak through Frank!Gateway; rollen
with these identities in Open Zaak are covered by tests/component/openzaak/test_statussen_rollen.py.
"""

from __future__ import annotations

import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KLAMER
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.basisregistraties import KVK_TEST_VESTIGING
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import expanded
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import partijen_of
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.zac import person_key
from podiumd_tests.zac import person_lookup
from podiumd_tests.zac import send_with_person
from podiumd_tests.zac import zaak_historie
from podiumd_tests.zac_betrokkenen import add_betrokkene
from podiumd_tests.zac_betrokkenen import betrokkene_roltype
from podiumd_tests.zac_betrokkenen import betrokkenen
from podiumd_tests.zac_betrokkenen import ontkoppel_betrokkene
from podiumd_tests.zac_betrokkenen import ontkoppel_initiator
from podiumd_tests.zac_betrokkenen import wijzig_initiator

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "keycloak")]

TA_REG_193 = pytest.mark.source(
    "TA regression/193-frankgateway-zac-openzaak-e2e.spec.ts",
    "A logged-in ZAC user's BRP and KvK lookups return the right data through ZAC's own client.",
)
REGRESSIE = pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, betrokkenen-klant).",
)
BEDRIJF = {"type": "VN", "kvkNummer": KVK_TEST_NUMMER, "vestigingsnummer": KVK_TEST_VESTIGING}


@TA_REG_193
@pytest.mark.scenario("""
    Given a behandelaar is logged in to ZAC
    When the behandelaar looks up a test person by BSN in the BRP
    Then ZAC finds exactly that person
    And shows the person's name
""")
def test_person_lookup(zac: requests.Session, urls: dict[str, str]) -> None:
    """ZAC finds a BRP test-set person by BSN, with the name (TA reg-193)."""
    personen = person_lookup(zac, urls["zac"], EREBOS)
    assert [p["bsn"] for p in personen] == [EREBOS]
    assert "Bultenaar" in str(personen[0]["naam"])


@TA_REG_193
@pytest.mark.tc("INT-004", "INT-005")
@pytest.mark.scenario("""
    Given a behandelaar is logged in to ZAC
    When the behandelaar looks up the test company by KvK number
    Then ZAC shows the company's basisprofiel with that KvK number
    And shows the company's name
""")
def test_company_lookup(zac: requests.Session, urls: dict[str, str]) -> None:
    """ZAC finds the KvK test company's basisprofiel by KvK number (TA reg-193)."""
    url = f"{urls['zac']}/rest/klanten/basisprofiel/{KVK_TEST_NUMMER}"
    bedrijf = expect_status(zac.get(url), HTTPStatus.OK).json()
    assert bedrijf["kvkNummer"] == KVK_TEST_NUMMER
    assert "Test BV Donald" in str(bedrijf.get("statutaireNaam") or bedrijf.get("eersteHandelsnaam"))


def _add_belanghebbende(zac: requests.Session, zac_url: str, zaak: JsonObject) -> requests.Response:
    roltype = betrokkene_roltype(zac, zac_url, zaak, "belanghebbende")
    return send_with_person(zac, zac_url, EREBOS, lambda person: add_betrokkene(zac, zac_url, zaak, roltype, person))


def _last_historie(zac: requests.Session, zac_url: str, zaak: JsonObject) -> tuple[object, object]:
    regel = zaak_historie(zac, zac_url, zaak)[0]
    return regel.get("actie"), regel.get("toelichting")


@REGRESSIE
@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC with a person as belanghebbende
    When the behandelaar adds the same person as belanghebbende again
    Then ZAC refuses it as already added
    And the zaak lists the person once
""")
def test_same_person_with_the_same_rol_is_added_once(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """A second betrokkene with the same BSN and roltype answers 409 (BetrokkeneIsAlreadyAddedToZaakException)."""
    zaak = zac_zaak()
    expect_status(_add_belanghebbende(zac, urls["zac"], zaak), HTTPStatus.OK)
    expect_status(_add_belanghebbende(zac, urls["zac"], zaak), HTTPStatus.CONFLICT)
    assert [betrokkene.get("bsn") for betrokkene in betrokkenen(zac, urls["zac"], zaak)] == [EREBOS]


@REGRESSIE
@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC with a person as belanghebbende
    When the behandelaar ontkoppelt the betrokkene with a reden
    Then the zaak no longer lists the betrokkene
    And the zaak's historie records the ontkoppeling with the reden
""")
def test_betrokkene_is_ontkoppeld_with_a_reden(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], registry: ResourceRegistry
) -> None:
    """ZAC deletes the rol; its historie shows ONTKOPPELD with the reden."""
    zaak = zac_zaak()
    expect_status(_add_belanghebbende(zac, urls["zac"], zaak), HTTPStatus.OK)
    betrokkene = betrokkenen(zac, urls["zac"], zaak)[0]
    reden = registry.tagged("ontkoppeld")
    expect_status(ontkoppel_betrokkene(zac, urls["zac"], betrokkene, reden), HTTPStatus.OK)
    assert betrokkenen(zac, urls["zac"], zaak) == []
    assert _last_historie(zac, urls["zac"], zaak) == ("ONTKOPPELD", reden)


@pytest.mark.xfail(
    strict=True,
    reason="[zac-13] ZAC 5.9.1 ontkoppelt a betrokkene without a reden (RestReden is not validated); not yet "
    "reported upstream",
)
@REGRESSIE
@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC with a person as belanghebbende
    When the behandelaar ontkoppelt the betrokkene without a reden
    Then ZAC refuses it
    And the zaak still lists the betrokkene
""")
def test_ontkoppelen_of_a_betrokkene_needs_a_reden(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """DELETE /rest/zaken/betrokkene/{rolid} without reden answers 400 and keeps the rol."""
    zaak = zac_zaak()
    expect_status(_add_belanghebbende(zac, urls["zac"], zaak), HTTPStatus.OK)
    betrokkene = betrokkenen(zac, urls["zac"], zaak)[0]
    response = ontkoppel_betrokkene(zac, urls["zac"], betrokkene, None)
    assert betrokkenen(zac, urls["zac"], zaak) == [betrokkene], f"ZAC answered {response.status_code}"
    expect_status(response, HTTPStatus.BAD_REQUEST)


def _initiator(openzaak: ApiClient, urls: dict[str, str], zaak: JsonObject) -> JsonObject:
    """The zaak's initiator rol in Open Zaak; fails unless there is exactly one."""
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}"})
    initiators = [rol for rol in rollen if rol.get("omschrijvingGeneriek") == "initiator"]
    assert len(initiators) == 1, initiators
    return initiators[0]


@REGRESSIE
@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC with a person as initiator
    When the behandelaar makes a bedrijf the initiator without a reden
    Then ZAC refuses it
    When the behandelaar makes the bedrijf the initiator with a reden
    Then Open Zaak has one initiator: a niet-natuurlijk persoon with only the KvK-nummer and vestigingsnummer
    When the behandelaar makes the person the initiator again with a reden
    Then Open Zaak has one initiator: the person
    When the behandelaar ontkoppelt the initiator with a reden
    Then the zaak has no initiator, and its historie records the reden
""")
def test_initiator_changes_from_persoon_to_bedrijf_and_back(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """Each change replaces the one initiator rol; a vestiging is stored as niet_natuurlijk_persoon without a name."""
    zaak = zac_zaak()
    zac_url = urls["zac"]

    def as_person(toelichting: str | None) -> requests.Response:
        return send_with_person(
            zac, zac_url, EREBOS, lambda person: wijzig_initiator(zac, zac_url, zaak, person, toelichting)
        )

    expect_status(as_person(None), HTTPStatus.OK)
    expect_status(wijzig_initiator(zac, zac_url, zaak, BEDRIJF, None), HTTPStatus.BAD_REQUEST)
    expect_status(wijzig_initiator(zac, zac_url, zaak, BEDRIJF, "podiumd-tests bedrijf"), HTTPStatus.OK)
    rol = _initiator(openzaak_productaanvraag, urls, zaak)
    assert rol["betrokkeneType"] == "niet_natuurlijk_persoon"
    filled = {key: value for key, value in section(rol, "betrokkeneIdentificatie").items() if value}
    assert filled == {"kvkNummer": KVK_TEST_NUMMER, "vestigingsNummer": KVK_TEST_VESTIGING}
    expect_status(as_person("podiumd-tests persoon"), HTTPStatus.OK)
    rol = _initiator(openzaak_productaanvraag, urls, zaak)
    assert section(rol, "betrokkeneIdentificatie").get("inpBsn") == EREBOS
    reden = registry.tagged("geen-initiator")
    ontkoppeld = expect_status(ontkoppel_initiator(zac, zac_url, zaak, reden), HTTPStatus.OK).json()
    assert ontkoppeld.get("initiatorIdentificatie") is None
    assert _last_historie(zac, zac_url, zaak) == ("ONTKOPPELD", reden)


@REGRESSIE
@pytest.mark.requires("openklant")
@pytest.mark.scenario("""
    Given a person in Open Klant with two e-mail addresses, neither of them the voorkeur
    When the behandelaar opens the person in ZAC
    Then ZAC shows the address Open Klant lists first
    When the other address becomes the voorkeur in Open Klant
    Then ZAC shows that address
""")
def test_person_e_mail_is_the_voorkeur_address_else_the_first(
    zac: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry
) -> None:
    """ZAC takes the e-mail address with isStandaardAdres, else the first of the partij's digitale adressen."""
    partij = make_partij(openklant, registry)
    make_partij_identificator(openklant, registry, partij, "bsn", KLAMER)
    assert partijen_of(openklant, KLAMER) == [partij["url"]], f"other Open Klant partijen have BSN {KLAMER}"
    for name in ("eerste", "tweede"):
        adres = f"{registry.tagged(name)}-{secrets.token_hex(2)}@example.invalid"
        make_digitaal_adres(openklant, registry, partij, adres, standaard=False)
    listed = expanded(openklant, str(partij["url"]), "digitaleAdressen")
    person = f"{urls['zac']}/rest/klanten/person/{person_key(zac, urls['zac'], KLAMER)}"

    def shown() -> object:
        return expect_status(zac.get(person), HTTPStatus.OK).json().get("emailadres")

    assert shown() == listed[0]["adres"]
    openklant.patch(str(listed[1]["url"]), {"isStandaardAdres": True})
    assert shown() == listed[1]["adres"]
