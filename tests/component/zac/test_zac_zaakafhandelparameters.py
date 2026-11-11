"""ZAC's zaakafhandelparameters: valide for the estate's zaaktypen, saved, copied to a new zaaktype version, and the
groups PABC authorises.

The estate's zaaktypen are only read. Saving, new versions and groups use throwaway zaaktypen of podiumd-tests' own
and run-tagged Keycloak groups.
"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.zac import EMAIL_CONFIRMATION
from podiumd_tests.json_data import differences
from podiumd_tests.json_data import section
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.openzaak import today
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.seed.zac_zaaktype import publish_new_version
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.zac import assignment
from podiumd_tests.zac import behandelaar_groups
from podiumd_tests.zac import clear_ztc_cache
from podiumd_tests.zac import comparable
from podiumd_tests.zac import copied_zaakafhandelparameters
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import inrichtingscheck_problems
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import read_zaakafhandelparameters
from podiumd_tests.zac import save_zaakafhandelparameters
from podiumd_tests.zac import zaakafhandelparameters

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
    url = f"{urls['openzaak']}/{ZAKEN}/zaken/{zaak['uuid']}"
    registry.add(f"zaak {zaak['identificatie']}", lambda: delete_zaak(openzaak, url))
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
