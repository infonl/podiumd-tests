"""ZAC's persons and companies: BRP and KvK lookups, betrokkenen and initiator of a zaak, contactgegevens from Open Klant.

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
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.mailpit import own_address
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openklant import expanded
from podiumd_tests.seed.openklant import make_digitaal_adres
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openklant import make_partij_identificator
from podiumd_tests.seed.openklant import partijen_of
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import INDEX_TIMEOUT
from podiumd_tests.zac import person_key
from podiumd_tests.zac import person_lookup
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import search
from podiumd_tests.zac import send_with_person
from podiumd_tests.zac import zaak_historie
from podiumd_tests.zac_betrokkenen import add_betrokkene
from podiumd_tests.zac_betrokkenen import betrokkene_roltype
from podiumd_tests.zac_betrokkenen import betrokkenen
from podiumd_tests.zac_betrokkenen import make_person_initiator
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
# BEDRIJF's betrokkeneIdentificatie in Open Zaak.
VESTIGING = {"kvkNummer": KVK_TEST_NUMMER, "vestigingsNummer": KVK_TEST_VESTIGING}
# The roltypen ZAC adds through their own actions, not as betrokkene (Betrokkenen.BETROKKENEN_ENUMSET).
NO_BETROKKENE = {"initiator", "behandelaar"}
# ZAC's search fields of a zaak's betrokkenen: all of them, and the prefix of those of one roltype.
ZAAK_BETROKKENEN = "ZAAK_BETROKKENEN"
BETROKKENE_VELD = "zaak_betrokkene_"
# A person of the BRP test set with an address in België.
IN_BELGIE = "999993483"


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


@REGRESSIE
# Persons of the BRP test set, each with one indication; ZAC adds OPSCHORTING_BIJHOUDING to each opschorting reden.
@pytest.mark.parametrize(
    ("bsn", "indicaties"),
    [
        pytest.param("999999655", {"OVERLEDEN", "OPSCHORTING_BIJHOUDING"}, id="overleden"),
        pytest.param("999991024", {"EMIGRATIE", "OPSCHORTING_BIJHOUDING"}, id="emigratie"),
        pytest.param("999993586", {"MINISTERIELE_REGELING", "OPSCHORTING_BIJHOUDING"}, id="ministeriele-regeling"),
        pytest.param("999996277", {"NIET_INGEZETENE"}, id="niet-ingezetene"),
        pytest.param("999990792", {"GEHEIMHOUDING_OP_PERSOONSGEGEVENS"}, id="geheimhouding"),
        pytest.param("999993355", {"IN_ONDERZOEK"}, id="in-onderzoek"),
        pytest.param("999990822", {"ONDER_CURATELE"}, id="curatele"),
    ],
)
@pytest.mark.scenario("""
    Given a person of the BRP test set with an indication, such as overleden or onder curatele
    When the behandelaar opens the person's details in ZAC
    Then ZAC shows exactly the indications the BRP gives for that person
""")
def test_person_shows_the_brp_indicaties(
    zac: requests.Session, urls: dict[str, str], bsn: str, indicaties: set[str]
) -> None:
    """GET klanten/person gives the indicaties ZAC derives from the BRP persoon."""
    shown = zac.get(f"{urls['zac']}/rest/klanten/person/{person_key(zac, urls['zac'], bsn)}")
    assert set(strings(expect_status(shown, HTTPStatus.OK).json().get("indicaties"))) == indicaties


@REGRESSIE
@pytest.mark.scenario("""
    Given a person of the BRP test set who lives in België
    When the behandelaar opens the person's details in ZAC
    Then ZAC shows the foreign address ending with the country
""")
def test_person_abroad_shows_the_country(zac: requests.Session, urls: dict[str, str]) -> None:
    """The verblijfplaats of a VerblijfplaatsBuitenland ends with its land."""
    shown = zac.get(f"{urls['zac']}/rest/klanten/person/{person_key(zac, urls['zac'], IN_BELGIE)}")
    assert str(expect_status(shown, HTTPStatus.OK).json().get("verblijfplaats")).endswith("België")


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


def _rol(openzaak: ApiClient, urls: dict[str, str], zaak: JsonObject, generiek: str = "initiator") -> JsonObject:
    """The zaak's rol in Open Zaak with this omschrijvingGeneriek; fails unless there is exactly one."""
    rollen = openzaak.list(f"{ZAKEN}/rollen", {"zaak": f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}"})
    found = [rol for rol in rollen if rol.get("omschrijvingGeneriek") == generiek]
    assert len(found) == 1, found
    return found[0]


def _bedrijf_identificatie(rol: JsonObject) -> JsonObject:
    """The filled fields of the rol's betrokkeneIdentificatie; fails unless it is a niet-natuurlijk persoon."""
    assert rol["betrokkeneType"] == "niet_natuurlijk_persoon"
    return {key: value for key, value in section(rol, "betrokkeneIdentificatie").items() if value}


@REGRESSIE
@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC with a person as initiator
    When the behandelaar makes a bedrijf the initiator without a reden
    Then ZAC refuses it
    When the behandelaar makes the bedrijf the initiator with a reden
    Then Open Zaak has one initiator: a niet-natuurlijk persoon with only the KvK-nummer and vestigingsnummer
    And the zaak's historie records the new initiator with the reden
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
    reden = registry.tagged("bedrijf")
    expect_status(wijzig_initiator(zac, zac_url, zaak, BEDRIJF, reden), HTTPStatus.OK)
    assert _bedrijf_identificatie(_rol(openzaak_productaanvraag, urls, zaak)) == VESTIGING
    assert _last_historie(zac, zac_url, zaak) == ("GEKOPPELD", reden)
    expect_status(as_person("podiumd-tests persoon"), HTTPStatus.OK)
    rol = _rol(openzaak_productaanvraag, urls, zaak)
    assert section(rol, "betrokkeneIdentificatie").get("inpBsn") == EREBOS
    reden = registry.tagged("geen-initiator")
    ontkoppeld = expect_status(ontkoppel_initiator(zac, zac_url, zaak, reden), HTTPStatus.OK).json()
    assert ontkoppeld.get("initiatorIdentificatie") is None
    assert _last_historie(zac, zac_url, zaak) == ("ONTKOPPELD", reden)


@pytest.mark.xfail(
    strict=True,
    reason="[zac-27] ZAC 5.9.1 answers 500 to an initiator with a vestigingsnummer and no kvkNummer "
    "(IllegalArgumentException in composeBetrokkeneIdentification); not yet reported upstream",
)
@REGRESSIE
@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar makes a vestiging without a KvK-nummer its initiator
    Then ZAC refuses it as a bad request
""")
def test_initiator_vestiging_needs_a_kvk_nummer(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """PATCH /rest/zaken/initiator of type VN without kvkNummer answers 400."""
    vestiging = {"type": "VN", "vestigingsnummer": KVK_TEST_VESTIGING}
    expect_status(wijzig_initiator(zac, urls["zac"], zac_zaak(), vestiging, None), HTTPStatus.BAD_REQUEST)


@pytest.mark.xfail(
    strict=True,
    reason="[zac-13] ZAC 5.9.1 ontkoppelt the initiator without a reden (RestReden is not validated); not yet "
    "reported upstream",
)
@REGRESSIE
@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC with a person as initiator
    When the behandelaar ontkoppelt the initiator without a reden
    Then ZAC refuses it
    And the zaak keeps its initiator
""")
def test_ontkoppelen_of_the_initiator_needs_a_reden(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """DELETE /rest/zaken/{uuid}/initiator without reden answers 400 and keeps the rol."""
    zaak = zac_zaak()
    zac_url = urls["zac"]
    make_person_initiator(zac, zac_url, zaak, EREBOS)
    response = ontkoppel_initiator(zac, zac_url, zaak, None)
    shown = read_zaak(zac, zac_url, str(zaak["uuid"]))
    assert section(shown, "initiatorIdentificatie").get("bsn") == EREBOS, f"ZAC answered {response.status_code}"
    expect_status(response, HTTPStatus.BAD_REQUEST)


@REGRESSIE
@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds a vestiging of a bedrijf as belanghebbende
    Then Open Zaak has the belanghebbende as a niet-natuurlijk persoon with only the KvK-nummer and vestigingsnummer
""")
def test_bedrijf_betrokkene_is_stored_with_its_kvk_and_vestigingsnummer(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    openzaak_productaanvraag: ApiClient,
) -> None:
    """ZAC stores a vestiging betrokkene as niet_natuurlijk_persoon with kvkNummer and vestigingsNummer, no name."""
    zaak = zac_zaak()
    roltype = betrokkene_roltype(zac, urls["zac"], zaak, "belanghebbende")
    expect_status(add_betrokkene(zac, urls["zac"], zaak, roltype, BEDRIJF), HTTPStatus.OK)
    rol = _rol(openzaak_productaanvraag, urls, zaak, "belanghebbende")
    assert _bedrijf_identificatie(rol) == VESTIGING


@REGRESSIE
@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar adds a betrokkene
    Then ZAC offers each roltype of the zaaktype but initiator and behandelaar, by name
""")
def test_betrokkene_roltypen_are_those_of_the_zaaktype(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaak: Callable[[], JsonObject],
    openzaak: ApiClient,
) -> None:
    """ZAC's betrokkene roltypen are the zaaktype's roltypen in Open Zaak without initiator and behandelaar."""
    zaaktype = section(zac_eigen_zaak(), "zaaktype")["uuid"]
    offered = get_entries(zac, f"{urls['zac']}/rest/klanten/roltype/{zaaktype}/betrokkene")
    zaaktype_url = f"{urls['openzaak']}/{CATALOGI}/zaaktypen/{zaaktype}"
    roltypen = openzaak.list(f"{CATALOGI}/roltypen", {"zaaktype": zaaktype_url})
    expected = [str(rol["omschrijving"]) for rol in roltypen if rol["omschrijvingGeneriek"] not in NO_BETROKKENE]
    assert [roltype["naam"] for roltype in offered] == sorted(expected)


@REGRESSIE
@pytest.mark.requires("openzaak", "opennotificaties")
@pytest.mark.scenario("""
    Given a zaak in ZAC with a person as initiator and a bedrijf as belanghebbende
    When the behandelaar opens the person and the bedrijf
    Then each lists the zaak with its betrokkenheid
    When their zaken are filtered on the roltype belanghebbende
    Then the bedrijf's list keeps the zaak and the person's list leaves it out
""")
def test_person_and_bedrijf_list_their_zaken_with_the_betrokkenheid(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject]
) -> None:
    """ZAC's search on zaak_betrokkenen (P-bsn, V-kvk-vestiging) finds the zaak; zaak_betrokkene_<roltype> narrows it."""
    zaak = zac_zaak()
    zac_url = urls["zac"]
    make_person_initiator(zac, zac_url, zaak, EREBOS)
    roltype = betrokkene_roltype(zac, zac_url, zaak, "belanghebbende")
    expect_status(add_betrokkene(zac, zac_url, zaak, roltype, BEDRIJF), HTTPStatus.OK)
    person, bedrijf = f"P-{EREBOS}", f"V-{KVK_TEST_NUMMER}-{KVK_TEST_VESTIGING}"

    def betrokkenheid(veld: str, klant: str) -> dict[str, list[str]] | None:
        query = {"ZAAK_IDENTIFICATIE": zaak["identificatie"], veld: klant}
        found = entries(search(zac, zac_url, type="ZAAK", zoeken=query)["resultaten"])
        match = next((item for item in found if item.get("id") == zaak["uuid"]), None)
        return None if match is None else {rol: strings(ids) for rol, ids in section(match, "betrokkenen").items()}

    listed = wait_until(
        lambda: betrokkenheid(ZAAK_BETROKKENEN, bedrijf),
        timeout=INDEX_TIMEOUT,
        description=f"zaak {zaak['identificatie']} indexed with its belanghebbende",
    )
    # The search lists betrokkenen by roltype naam, _ for spaces.
    rol = str(roltype["naam"]).replace(" ", "_")
    assert listed.get(rol) == [bedrijf], listed
    assert any(person in ids for ids in listed.values()), listed
    assert betrokkenheid(ZAAK_BETROKKENEN, person) is not None
    assert betrokkenheid(BETROKKENE_VELD + rol, bedrijf) is not None
    assert betrokkenheid(BETROKKENE_VELD + rol, person) is None


@REGRESSIE
@pytest.mark.requires("openklant")
@pytest.mark.scenario("""
    Given a person in Open Klant with two e-mail addresses and two telefoonnummers, none of them the voorkeur
    When the behandelaar opens the person in ZAC
    Then ZAC shows the e-mail address and the telefoonnummer Open Klant lists first
    When the other e-mail address and telefoonnummer become the voorkeur in Open Klant
    Then ZAC shows those
""")
def test_person_contactgegevens_are_the_voorkeur_else_the_first(
    zac: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry
) -> None:
    """ZAC takes the e-mail address and telefoonnummer with isStandaardAdres, else the first of each soort."""
    partij = make_partij(openklant, registry)
    make_partij_identificator(openklant, registry, partij, "bsn", KLAMER)
    assert partijen_of(openklant, KLAMER) == [partij["url"]], f"other Open Klant partijen have BSN {KLAMER}"
    for _ in range(2):
        make_digitaal_adres(openklant, registry, partij, own_address(registry), standaard=False)
        make_digitaal_adres(openklant, registry, partij, f"06{secrets.randbelow(10**8):08d}", standaard=False)
    listed = expanded(openklant, str(partij["url"]), "digitaleAdressen")
    soorten = {
        veld: [adres for adres in listed if adres["soortDigitaalAdres"] == soort]
        for veld, soort in (("emailadres", "email"), ("telefoonnummer", "telefoonnummer"))
    }
    person = f"{urls['zac']}/rest/klanten/person/{person_key(zac, urls['zac'], KLAMER)}"

    def shown() -> dict[str, object]:
        found = expect_status(zac.get(person), HTTPStatus.OK).json()
        return {veld: found.get(veld) for veld in soorten}

    assert shown() == {veld: adressen[0]["adres"] for veld, adressen in soorten.items()}
    for adressen in soorten.values():
        openklant.patch(str(adressen[1]["url"]), {"isStandaardAdres": True})
    assert shown() == {veld: adressen[1]["adres"] for veld, adressen in soorten.items()}
