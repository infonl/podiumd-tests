"""ZAC's zaakafhandelparameters: valide for the estate's zaaktypen, saved, copied to a new zaaktype version, and the
groups PABC authorises.

The estate's zaaktypen are only read. Saving, new versions and groups use throwaway zaaktypen of podiumd-tests' own
and run-tagged Keycloak groups.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.zac import EMAIL_CONFIRMATION
from podiumd_tests.json_data import differences
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import describe
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import today
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.seed.zac_zaaktype import publish_new_version
from podiumd_tests.seed.zac_zaaktype import publish_zac_zaaktype
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.seed.zac_zaaktype import zac_catalogus
from podiumd_tests.zac import assignment
from podiumd_tests.zac import behandelaar_groups
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import clear_ztc_cache
from podiumd_tests.zac import comparable
from podiumd_tests.zac import configure_zaaktype
from podiumd_tests.zac import copied_zaakafhandelparameters
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import inrichtingscheck_problems
from podiumd_tests.zac import put_zaakafhandelparameters
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import read_zaakafhandelparameters
from podiumd_tests.zac import save_zaakafhandelparameters
from podiumd_tests.zac import send_with_person
from podiumd_tests.zac import user_groups
from podiumd_tests.zac import zaak_body
from podiumd_tests.zac import zaakafhandelparameters
from podiumd_tests.zac_betrokkenen import wijzig_initiator

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "keycloak"),
]

PI = pytest.mark.source(
    "PI test_zac_zaakafhandelparameters.py",
    "A published zaaktype is unusable in ZAC until its zaakafhandelparameters are valide; guards against a reseed losing them.",
)
ZAC_TEAM = pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, beheer-zaps).",
)
# A throwaway zaaktype is made known to PABC and deleted with a Django snippet.
THROWAWAY = pytest.mark.requires("pabc", "cluster")
# The tests of fixture zac_eigen_zaaktype.
EIGEN_ZAAKTYPE = pytest.mark.xdist_group("zac-eigen-zaaktype")
# Tests that read every zaaktype of ZAC's catalogus, where test_zac_catalogus.py publishes some.
ZAC_CATALOGUS = pytest.mark.xdist_group("zac-catalogus")
# A bedrijf from the KvK as BetrokkeneIdentificatie.
BEDRIJF = {"type": "RSIN", "kvkNummer": KVK_TEST_NUMMER}


@PI
@pytest.mark.scenario("""
    Given the zaaktype for productaanvragen is published in Open Zaak
    When the beheerder opens its zaakafhandelparameters in ZAC
    Then ZAC reports them as valide
""")
def test_zaakafhandelparameters_are_valide(
    zac: requests.Session, urls: dict[str, str], openzaak: ApiClient, podiumd_env: Environment
) -> None:
    """ZAC reports its zaakafhandelparameters for the productaanvraag zaaktype as valide (PI)."""
    identificatie = podiumd_env.profile.settings.get("productaanvraag_zaaktype")
    if not identificatie:
        pytest.skip(f"profile {podiumd_env.profile.name} has no settings.productaanvraag_zaaktype")
    zaaktypen = openzaak.list(f"{CATALOGI}/zaaktypen", {"identificatie": identificatie, "status": "definitief"})
    assert zaaktypen, f"no published zaaktype {identificatie} in Open Zaak"
    for zaaktype in zaaktypen:
        assert read_zaakafhandelparameters(zac, urls["zac"], uuid_of(zaaktype["url"]))["valide"], zaaktype["url"]


@PI
@ZAC_CATALOGUS
@pytest.mark.scenario("""
    Given ZAC has zaakafhandelparameters for a set of zaaktypen
    When the beheerder clears ZAC's catalogus cache and runs the inrichtingscheck
    Then none of those zaaktypen fails the inrichtingscheck
""")
def test_handled_zaaktypen_pass_zacs_inrichtingscheck(zac: requests.Session, urls: dict[str, str]) -> None:
    """Every zaaktype ZAC has zaakafhandelparameters for passes ZAC's own inrichtingscheck (Admin, Inrichtingscheck).

    The check covers what ZAC needs of a zaaktype in Open Zaak, e.g. an informatieobjecttype "e-mail",
    without which ZAC fails after sending a mail when it stores the mail with the zaak.
    """
    # ZAC caches catalogus data; clear it (Admin, as after changing a zaaktype) so the check sees Open Zaak's state.
    clear_ztc_cache(zac, urls["zac"])
    handled = {section(p, "zaaktype").get("identificatie") for p in zaakafhandelparameters(zac, urls["zac"])}
    checks = get_entries(zac, f"{urls['zac']}/rest/health-check/zaaktypes")
    failing = {
        str(section(c, "zaaktype").get("identificatie")): problems
        for c in checks
        if section(c, "zaaktype").get("identificatie") in handled and (problems := inrichtingscheck_problems(c))
    }
    assert not failing, f"ZAC's inrichtingscheck fails: {failing}"


def _fill_in(zac: requests.Session, zac_url: str, parameters: JsonObject) -> dict[str, object]:
    """Save a value other than ZAC's default in every part the beheerder fills in; the values saved."""
    reden = get_entries(zac, f"{zac_url}/rest/zaakafhandelparameters/zaakbeeindigredenen")[0]
    wanted: dict[str, object] = {
        "defaultBehandelaarId": ADMIN.username,
        "einddatumGeplandWaarschuwing": 0,
        "uiterlijkeEinddatumAfdoeningWaarschuwing": 31,
        "intakeMail": "NIET_BESCHIKBAAR",
        "afrondenMail": "BESCHIKBAAR_UIT",
        "zaakbeeindigParameters": [
            {"zaakbeeindigReden": reden, "resultaattype": parameters["zaakNietOntvankelijkResultaattype"]}
        ],
        "zaakAfzenders": [{"mail": "GEMEENTE", "defaultMail": True, "replyTo": "GEMEENTE", "speciaal": True}],
        "automaticEmailConfirmation": dict(EMAIL_CONFIRMATION.wanted),
        "betrokkeneKoppelingen": {"brpKoppelen": True, "kvkKoppelen": False},
    }
    save_zaakafhandelparameters(zac, zac_url, {**parameters, **wanted})
    return wanted


def _uuid(parameters: JsonObject) -> str:
    return str(section(parameters, "zaaktype")["uuid"])


@ZAC_TEAM
@THROWAWAY
@EIGEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaaktype configured in ZAC
    When the beheerder saves a default behandelaar, waarschuwingsvensters of 0 and 31 days and a zaakbeeindig reden
    And statusmails, an afzender with reply-to, the ontvangstbevestiging and the BRP and KvK koppelingen
    Then ZAC gives back every saved value when the zaakafhandelparameters are read again
""")
def test_saved_zaakafhandelparameters_are_read_back(
    zac: requests.Session, urls: dict[str, str], zac_eigen_zaaktype: JsonObject
) -> None:
    """Every part of the zaakafhandelparameters the beheerder saves is read back unchanged."""
    uuid = _uuid(zac_eigen_zaaktype)
    wanted = _fill_in(zac, urls["zac"], read_zaakafhandelparameters(zac, urls["zac"], uuid))
    assert differences(wanted, read_zaakafhandelparameters(zac, urls["zac"], uuid)) == []


def _zaak(
    zac: requests.Session, urls: dict[str, str], openzaak: ApiClient, registry: ResourceRegistry, parameters: JsonObject
) -> JsonObject:
    """Start a zaak in ZAC in the default groep of these zaakafhandelparameters; cleanup deletes it."""
    zaak = create_zaak(zac, urls["zac"], parameters, omschrijving=registry.tagged("zac-versie"))
    clean_up_zaak(zac, urls["zac"], openzaak, registry, zaak, with_documents=False)
    return zaak


@ZAC_TEAM
@THROWAWAY
@pytest.mark.scenario("""
    Given a zaaktype configured in ZAC with every part of its zaakafhandelparameters filled in, and a zaak of it
    When a new version of the zaaktype is published in Open Zaak, and the old one ends yesterday
    Then ZAC gives the new version the same zaakafhandelparameters
    When the beheerder changes the default groep of the new version
    Then a new zaak gets that groep
    And the zaak of the old version keeps its groep
""")
def test_new_zaaktype_version_keeps_the_zaakafhandelparameters(
    podiumd_env: Environment,
    urls: dict[str, str],
    openzaak: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
    need_bootstrap: Callable[..., None],
) -> None:
    """ZAC copies the zaakafhandelparameters to a new zaaktype version (as for podiumd-chart-37); a new default groep
    leaves existing zaken alone.
    """
    need_bootstrap("zac-bpmn-process")
    zac_url = urls["zac"]
    begin = (date.fromisoformat(today()) - timedelta(days=7)).isoformat()
    # ZAC copies the einddatum gepland waarschuwing only to a version with a servicenorm.
    oud = make_zac_zaaktype(
        podiumd_env, openzaak, registry, test_zaaktype, beginGeldigheid=begin, versiedatum=begin, servicenorm="P10D"
    )
    # A login after make_zac_zaaktype: ZAC reads the rights on the zaaktype from PABC at login.
    zac = zac_as_admin(podiumd_env)
    _fill_in(zac, zac_url, oud)
    oud = read_zaakafhandelparameters(zac, zac_url, _uuid(oud))
    oude_zaak = _zaak(zac, urls, openzaak, registry, oud)

    zaaktype = openzaak.get(f"{urls['openzaak']}/{CATALOGI}/zaaktypen/{_uuid(oud)}")
    nieuw = publish_new_version(podiumd_env, openzaak, registry, test_zaaktype, zaaktype)
    copied = copied_zaakafhandelparameters(zac, zac_url, uuid_of(nieuw["url"]))
    assert comparable(copied) == comparable(oud)

    groep = str(oud["defaultGroepId"])
    andere = sorted(behandelaar_groups(zac, zac_url, str(zaaktype["omschrijving"])) - {groep})
    if not andere:
        pytest.skip(f"PABC authorises no group but {groep} for zaaktype {zaaktype['omschrijving']}")
    gewijzigd = save_zaakafhandelparameters(
        zac, zac_url, {**copied, "defaultGroepId": andere[0], "defaultBehandelaarId": None}
    )
    nieuwe_zaak = _zaak(zac, urls, openzaak, registry, gewijzigd)
    assert assignment(read_zaak(zac, zac_url, str(nieuwe_zaak["uuid"])))[0] == andere[0]
    assert assignment(read_zaak(zac, zac_url, str(oude_zaak["uuid"])))[0] == groep


@ZAC_TEAM
@THROWAWAY
@EIGEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaaktype in podiumd-tests' PABC domain
    And a Keycloak group with podiumd-tests' behandelaar role and one with its raadpleger role in that domain
    When the beheerder lists the groups that may handle zaken of the zaaktype
    Then ZAC offers the behandelaar group and not the raadpleger group
    And for a zaaktype outside the domain it offers neither
""")
def test_zac_offers_the_groups_pabc_authorises_as_behandelaar(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaaktype: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """ZAC's behandelaar groups of a zaaktype are those whose realm roles PABC maps to behandelaar for it."""
    behandelaars = make_role_group(podiumd_env, registry, "behandelaar")
    raadplegers = make_role_group(podiumd_env, registry, "raadpleger")
    offered = behandelaar_groups(zac, urls["zac"], str(section(zac_eigen_zaaktype, "zaaktype")["omschrijving"]))
    assert (behandelaars in offered, raadplegers in offered) == (True, False)
    outside = behandelaar_groups(zac, urls["zac"], registry.tagged("buiten-domein"))
    assert not {behandelaars, raadplegers} & outside


@ZAC_TEAM
@THROWAWAY
@EIGEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaaktype configured in ZAC, and the estate's zaaktype for productaanvragen with its productaanvraagtype
    When the beheerder saves that productaanvraagtype, or an empty one, on the zaaktype
    Then ZAC refuses both
    When the beheerder saves a productaanvraagtype of its own, and then none
    Then ZAC reads back that productaanvraagtype, and then none
""")
def test_productaanvraagtype_is_unique_and_can_be_cleared(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaaktype: JsonObject,
    zac_parameters: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """ZAC refuses a productaanvraagtype another zaaktype has, and an empty one; None clears it."""
    bezet = zac_parameters.get("productaanvraagtype")
    if not bezet:
        pytest.skip(f"zaaktype {section(zac_parameters, 'zaaktype').get('identificatie')} has no productaanvraagtype")
    zac_url, uuid = urls["zac"], _uuid(zac_eigen_zaaktype)
    parameters = read_zaakafhandelparameters(zac, zac_url, uuid)
    answers = {
        waarde: put_zaakafhandelparameters(zac, zac_url, {**parameters, "productaanvraagtype": waarde})
        for waarde in (bezet, "")
    }
    assert {waarde: answer.status_code for waarde, answer in answers.items()} == dict.fromkeys(
        answers, HTTPStatus.BAD_REQUEST
    ), {waarde: describe(answer) for waarde, answer in answers.items()}
    eigen = registry.tagged("aanvraag")
    for waarde in (eigen, None):
        # The saved parameters: ZAC refuses a save of the ones it replaced.
        parameters = save_zaakafhandelparameters(zac, zac_url, {**parameters, "productaanvraagtype": waarde})
        assert read_zaakafhandelparameters(zac, zac_url, uuid).get("productaanvraagtype") == waarde


def _koppelingen(zac: requests.Session, zac_url: str, uuid: str, **koppelingen: object) -> JsonObject:
    """Save these BRP and KvK koppelingen on the zaaktype's current zaakafhandelparameters; the saved ones."""
    parameters = read_zaakafhandelparameters(zac, zac_url, uuid)
    wanted = {**section(parameters, "betrokkeneKoppelingen"), **koppelingen}
    return save_zaakafhandelparameters(zac, zac_url, {**parameters, "betrokkeneKoppelingen": wanted})


def _koppelingen_for_test(
    zac: requests.Session, zac_url: str, uuid: str, registry: ResourceRegistry, **koppelingen: object
) -> JsonObject:
    """_koppelingen; cleanup restores the current values in the row the zaaktype has then."""
    current = section(read_zaakafhandelparameters(zac, zac_url, uuid), "betrokkeneKoppelingen")
    before = {key: value for key, value in current.items() if key != "id"}
    registry.add(f"koppelingen of {uuid}", lambda: _koppelingen(zac, zac_url, uuid, **before))
    return _koppelingen(zac, zac_url, uuid, **koppelingen)


@ZAC_TEAM
@THROWAWAY
@EIGEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaaktype configured in ZAC with the BRP and KvK koppelingen off
    When the behandelaar starts a zaak of it with a bedrijf from the KvK, or a person from the BRP, as initiator
    Then ZAC refuses both
    When the beheerder turns the KvK koppeling on
    Then a zaak of it starts with the bedrijf as initiator
""")
def test_koppelingen_decide_the_initiator_of_a_new_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaaktype: JsonObject,
    openzaak: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """ZAC refuses an initiator type whose koppeling is off (ZaakRestService.assertCanAddBetrokkene)."""
    zac_url, uuid = urls["zac"], _uuid(zac_eigen_zaaktype)
    uit = _koppelingen_for_test(zac, zac_url, uuid, registry, brpKoppelen=False, kvkKoppelen=False)
    omschrijving = registry.tagged("koppeling")

    def start(initiator: JsonObject) -> requests.Response:
        body = zaak_body(uit, omschrijving=omschrijving, initiatorIdentificatie=initiator)
        return zac.post(f"{zac_url}/rest/zaken/zaak", json=body)

    answers = {"bedrijf": start(BEDRIJF), "persoon": send_with_person(zac, zac_url, EREBOS, start)}
    assert {soort: answer.status_code for soort, answer in answers.items()} == dict.fromkeys(
        answers, HTTPStatus.BAD_REQUEST
    ), {soort: describe(answer) for soort, answer in answers.items()}

    kvk = _koppelingen(zac, zac_url, uuid, kvkKoppelen=True)
    zaak = create_zaak(zac, zac_url, kvk, omschrijving=omschrijving, initiatorIdentificatie=BEDRIJF)
    clean_up_zaak(zac, zac_url, openzaak, registry, zaak, with_documents=False)
    assert section(zaak, "initiatorIdentificatie").get("kvkNummer") == KVK_TEST_NUMMER


@pytest.mark.xfail(
    strict=True,
    reason="[zac-24] ZAC 5.9.1 checks the BRP and KvK koppelingen only when a zaak is created or updated, not in "
    "updateInitiator and addBetrokkene; not yet reported upstream",
)
@ZAC_TEAM
@THROWAWAY
@EIGEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaak of a zaaktype configured in ZAC with the KvK koppeling off
    When the behandelaar makes a bedrijf from the KvK its initiator
    Then ZAC refuses it
""")
def test_koppelingen_decide_the_initiator_of_an_existing_zaak(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaaktype: JsonObject,
    zac_eigen_zaak: Callable[[], JsonObject],
    registry: ResourceRegistry,
) -> None:
    """PATCH /rest/zaken/initiator with a KvK initiator answers 400 while kvkKoppelen is false."""
    zac_url = urls["zac"]
    _koppelingen_for_test(zac, zac_url, _uuid(zac_eigen_zaaktype), registry, kvkKoppelen=False)
    response = wijzig_initiator(zac, zac_url, zac_eigen_zaak(), BEDRIJF, None)
    assert response.status_code == HTTPStatus.BAD_REQUEST, describe(response)


@pytest.mark.xfail(
    strict=True,
    reason="[zac-26] ZAC 5.9.1 answers 500 msg.error.server.generic to zaakafhandelparameters read before a save "
    "that replaced their koppelingen (Row was already updated or deleted: ZaaktypeBetrokkeneParameters); not yet "
    "reported upstream",
)
@ZAC_TEAM
@THROWAWAY
@EIGEN_ZAAKTYPE
@pytest.mark.scenario("""
    Given a zaaktype configured in ZAC whose zaakafhandelparameters two beheerders opened
    When the first beheerder saves new BRP and KvK koppelingen
    And the second beheerder saves the copy opened before that
    Then ZAC refuses the second save as a bad request or a conflict
""")
def test_outdated_zaakafhandelparameters_are_refused(
    zac: requests.Session, urls: dict[str, str], zac_eigen_zaaktype: JsonObject, registry: ResourceRegistry
) -> None:
    """A PUT of zaakafhandelparameters whose koppelingen a later save replaced answers 400 or 409."""
    zac_url, uuid = urls["zac"], _uuid(zac_eigen_zaaktype)
    oud = read_zaakafhandelparameters(zac, zac_url, uuid)
    kvk = not section(oud, "betrokkeneKoppelingen").get("kvkKoppelen")
    # Without their id ZAC stores the koppelingen as a new row.
    _koppelingen_for_test(zac, zac_url, uuid, registry, id=None, kvkKoppelen=kvk)
    response = put_zaakafhandelparameters(zac, zac_url, oud)
    assert response.status_code in {HTTPStatus.BAD_REQUEST, HTTPStatus.CONFLICT}, describe(response)


@ZAC_TEAM
@THROWAWAY
@pytest.mark.scenario("""
    Given a zaaktype just published in Open Zaak, not yet configured in ZAC
    When the beheerder opens its zaakafhandelparameters
    Then they are empty and not valide, without creatiedatum
    And the afzenders gemeente and medewerker are offered
    When the beheerder saves them
    Then they have today as creatiedatum
""")
def test_new_zaaktype_has_empty_zaakafhandelparameters(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """ZAC answers a zaaktype without zaakafhandelparameters with its defaults: no id, model, groep or creatiedatum."""
    zaaktype = publish_zac_zaaktype(podiumd_env, openzaak, registry, test_zaaktype)
    uuid = uuid_of(zaaktype["url"])
    found = read_zaakafhandelparameters(zac, urls["zac"], uuid)
    fields = ("id", "valide", "caseDefinition", "defaultGroepId", "humanTaskParameters", "creatiedatum")
    assert {field: found.get(field) for field in fields} == {
        "id": None,
        "valide": False,
        "caseDefinition": None,
        "defaultGroepId": None,
        "humanTaskParameters": [],
        "creatiedatum": None,
    }
    assert {str(afzender.get("mail")) for afzender in entries(found.get("zaakAfzenders"))} == {"GEMEENTE", "MEDEWERKER"}
    saved = configure_zaaktype(zac, urls["zac"], uuid, user_groups(zac, urls["zac"])[0])
    assert str(saved.get("creatiedatum")).startswith(today())


@ZAC_TEAM
@ZAC_CATALOGUS
@pytest.mark.requires("cluster")
@pytest.mark.scenario("""
    Given the zaaktypen of ZAC's own catalogus in Open Zaak
    When the beheerder opens the list of zaakafhandelparameters
    Then ZAC lists each of those zaaktypen
    And each configured one with its creatiedatum
""")
def test_zaakafhandelparameters_list_the_zaaktypen_of_zacs_catalogus(
    podiumd_env: Environment, zac: requests.Session, urls: dict[str, str], openzaak: ApiClient
) -> None:
    """GET zaakafhandelparameters lists the zaaktypen of catalogus CATALOGUS_DOMEIN; creatiedatum is set iff id is."""
    catalogus = zac_catalogus(podiumd_env, openzaak)
    zaaktypen = openzaak.list(f"{CATALOGI}/zaaktypen", {"catalogus": str(catalogus["url"])})
    listed = get_entries(zac, f"{urls['zac']}/rest/zaakafhandelparameters")
    # ZAC lists only the first page of Open Zaak's answer: 100 zaaktypen.
    assert {str(section(item, "zaaktype")["uuid"]) for item in listed} == {
        uuid_of(zaaktype["url"]) for zaaktype in zaaktypen[:100]
    }
    assert [item for item in listed if (item.get("id") is None) != (item.get("creatiedatum") is None)] == []
