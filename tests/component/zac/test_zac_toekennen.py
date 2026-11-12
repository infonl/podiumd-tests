"""ZAC's assignment of zaken and taken to a group and behandelaar, one at a time and from the werkvoorraad list.

Ported from ZAC's own e2e features zaken-verdelen-vrijgeven and bpmn (toekennen), through the REST API its UI calls.
"""

from __future__ import annotations

from collections import Counter
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import INTAKE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.zac_zaaktype import make_other_domain_group
from podiumd_tests.seed.zac_zaaktype import make_role_group
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import LIST_TIMEOUT
from podiumd_tests.zac import afhandelen
from podiumd_tests.zac import afronden_intake
from podiumd_tests.zac import assignment
from podiumd_tests.zac import behandelaar_groups
from podiumd_tests.zac import listed_assignment
from podiumd_tests.zac import open_task
from podiumd_tests.zac import read_taak
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import search_all
from podiumd_tests.zac import taak_toekennen_mij
from podiumd_tests.zac import toekennen
from podiumd_tests.zac import toekennen_mij
from podiumd_tests.zac import toekennen_taak
from podiumd_tests.zac import verdelen
from podiumd_tests.zac import verdelen_taken
from podiumd_tests.zac import vrijgeven
from podiumd_tests.zac import zaaktype_filter
from podiumd_tests.zac_signaleringen import signalering_mail

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]

# More zaken than one page of ZAC's werklijsten (WERKLIJST_ROWS).
BULK = 100
WERKLIJST_ROWS = 25
# ZAC indexes, assigns and releases BULK zaken one by one: its job assigned 63 in 120 s on minikube.
BULK_TIMEOUT = 600
ZAC_TEAM = pytest.mark.source(
    "podiumd-tests",
    "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md,"
    " zoeken-werklijsten-dashboard).",
)


@pytest.mark.source("ZAC features/9-bpmn.feature", "Bob changes the group and user a zaak is assigned to.")
@pytest.mark.scenario("""
    Given a zaak in ZAC
    When the behandelaar assigns the zaak to a group and a behandelaar
    Then the zaak has that group and behandelaar
""")
def test_zaak_is_assigned_to_a_group_and_behandelaar(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], zac_group: str
) -> None:
    """Toekennen gives the zaak the chosen group and behandelaar."""
    zaak = zac_zaak()
    assigned = expect_status(toekennen(zac, urls["zac"], zaak, zac_group, ADMIN.username), HTTPStatus.OK).json()
    assert assignment(assigned) == (zac_group, ADMIN.username)


@pytest.mark.source(
    "ZAC features/6-zaken-verdelen-vrijgeven.feature",
    "Bob assigns selected zaken from the werkvoorraad to a group and user, and releases them.",
)
@pytest.mark.scenario("""
    Given two zaken in ZAC
    When the behandelaar assigns both from the werkvoorraad to a group and a behandelaar
    Then both zaken have that group and behandelaar
    When the behandelaar releases both zaken
    Then both zaken keep the group but have no behandelaar
""")
def test_zaken_from_the_list_are_assigned_and_released(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], zac_group: str
) -> None:
    """Verdelen gives the selected zaken the group and behandelaar; vrijgeven takes the behandelaar away again."""
    uuids = [str(zac_zaak()["uuid"]), str(zac_zaak()["uuid"])]

    def are_all(wanted: tuple[object, object]) -> bool:
        return all(assignment(read_zaak(zac, urls["zac"], u)) == wanted for u in uuids)

    expect_status(verdelen(zac, urls["zac"], uuids, zac_group, ADMIN.username), HTTPStatus.NO_CONTENT)
    wait_until(lambda: are_all((zac_group, ADMIN.username)), timeout=LIST_TIMEOUT, description="zaken verdeeld")
    expect_status(vrijgeven(zac, urls["zac"], uuids), HTTPStatus.NO_CONTENT)
    wait_until(lambda: are_all((zac_group, None)), timeout=LIST_TIMEOUT, description="zaken vrijgegeven")


@ZAC_TEAM
@pytest.mark.scenario("""
    Given a zaak in ZAC assigned to the test admin and the admin's group
    When the coordinator assigns it from the werkvoorraad to another group, without a behandelaar
    Then the zaak has that group and no behandelaar
""")
def test_zaak_verdeeld_to_a_group_alone_loses_its_behandelaar(
    zac: requests.Session,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    zac_group: str,
    zac_parameters: JsonObject,
) -> None:
    """Verdelen with a group and no behandelaar removes the behandelaar's rol (ZaakService.changeBehandelaar)."""
    groep = str(zac_parameters["defaultGroepId"])
    if groep == zac_group:
        pytest.skip(f"the zaaktype's default group is the test admin's group {groep}")
    zaak = zac_zaak()
    expect_status(toekennen(zac, urls["zac"], zaak, zac_group, ADMIN.username), HTTPStatus.OK)
    expect_status(verdelen(zac, urls["zac"], [str(zaak["uuid"])], groep, None), HTTPStatus.NO_CONTENT)
    wait_until(
        lambda: assignment(read_zaak(zac, urls["zac"], str(zaak["uuid"]))) == (groep, None),
        timeout=LIST_TIMEOUT,
        description=f"zaak {zaak['identificatie']} verdeeld to {groep}",
    )


@pytest.mark.slow
@pytest.mark.xdist_group("zac-eigen-zaaktype")
@pytest.mark.source("podiumd-tests", "Verdelen and vrijgeven of more zaken than one werklijst page.")
@pytest.mark.scenario("""
    Given 100 zaken of a zaaktype of their own in the werkvoorraad
    When the behandelaar assigns all of them to a group and a behandelaar
    Then the werkvoorraad lists all 100 with that group and behandelaar
    When the behandelaar releases all of them
    Then the werkvoorraad lists all 100 with that group and no behandelaar
""")
def test_hundred_zaken_are_assigned_and_released(
    zac: requests.Session,
    urls: dict[str, str],
    zac_eigen_zaaktype: JsonObject,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    zac_group: str,
) -> None:
    """Verdelen and vrijgeven of BULK zaken reach each of them, as the werkvoorraad lists them page by page."""
    zaaktype = section(zac_eigen_zaaktype, "zaaktype")
    zaaktype_url = openzaak.url(f"{CATALOGI}/zaaktypen/{zaaktype['uuid']}")
    uuids = sorted(str(make_zaak(openzaak, registry, zaaktype_url)["uuid"]) for _ in range(BULK))
    query = {"type": "ZAAK", "alleenOpenstaandeZaken": True, "filters": zaaktype_filter(str(zaaktype["omschrijving"]))}

    def are_all(wanted: tuple[object, object] | None) -> bool:
        """None: any assignment. On a mismatch, wait_until reports the listed assignments' counts."""
        found = search_all(zac, urls["zac"], WERKLIJST_ROWS, **query)
        listed = {str(item["id"]): listed_assignment(item) for item in found}
        assert sorted(listed) == uuids, f"listed {len(listed)} of {BULK} zaken"
        assert wanted is None or set(listed.values()) == {wanted}, f"listed {Counter(listed.values())}"
        return True

    wait_until(lambda: are_all(None), timeout=BULK_TIMEOUT, description=f"{BULK} zaken in the werkvoorraad")
    expect_status(verdelen(zac, urls["zac"], uuids, zac_group, ADMIN.username), HTTPStatus.NO_CONTENT)
    wait_until(lambda: are_all((zac_group, ADMIN.username)), timeout=BULK_TIMEOUT, description=f"{BULK} zaken verdeeld")
    expect_status(vrijgeven(zac, urls["zac"], uuids), HTTPStatus.NO_CONTENT)
    wait_until(lambda: are_all((zac_group, None)), timeout=BULK_TIMEOUT, description=f"{BULK} zaken vrijgegeven")


@ZAC_TEAM
@pytest.mark.requires("pabc", "mailpit", "opennotificaties")
@pytest.mark.xdist_group("zac-signaleringen")
@pytest.mark.scenario("""
    Given the test admin wants a mail, and no dashboard signal, for zaken put on their name
    And three zaken: one without behandelaar, one already on the admin's name, one afgehandeld
    When the coordinator assigns all three from the werkvoorraad to the admin's group and the admin
    Then both open zaken have that group and the admin
    And the admin gets a mail for the zaak that had no behandelaar
    And the afgehandelde zaak keeps no behandelaar
""")
def test_verdelen_assigns_the_open_zaken_mails_the_behandelaar_and_skips_a_closed_one(  # three zaken, mail
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_zaak: Callable[..., JsonObject],
    zac_group: str,
    signaleringen: Callable[..., None],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """ZaakService.assignZaken skips a zaak that is not open; the new behandelaar gets ZAAK_OP_NAAM by mail."""
    zac_url = urls["zac"]
    signaleringen(mail=True, ZAAK_OP_NAAM=False)
    on_admin, closed = zac_zaak(), zac_zaak()
    expect_status(toekennen(zac, zac_url, on_admin, zac_group, ADMIN.username), HTTPStatus.OK)
    afronden_intake(zac, zac_url, closed)
    expect_status(afhandelen(zac, zac_url, closed), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    closed_before = assignment(read_zaak(zac, zac_url, str(closed["uuid"])))
    uuids = [str(zaak["uuid"]) for zaak in (bpmn_zaak, on_admin, closed)]

    expect_status(verdelen(zac_as("coordinator"), zac_url, uuids, zac_group, ADMIN.username), HTTPStatus.NO_CONTENT)
    wait_until(
        lambda: all(assignment(read_zaak(zac, zac_url, u)) == (zac_group, ADMIN.username) for u in uuids[:2]),
        timeout=LIST_TIMEOUT,
        description="open zaken verdeeld",
    )
    signalering_mail(mailpit, registry, ADMIN.username, str(bpmn_zaak["identificatie"]), timeout=LIST_TIMEOUT)
    assert assignment(read_zaak(zac, zac_url, uuids[2])) == closed_before


@ZAC_TEAM
@pytest.mark.scenario("""
    Given a zaak in ZAC without behandelaar
    When the test admin assigns it to themselves from the werkvoorraad, in their group
    Then the zaak has that group and the admin as behandelaar
""")
def test_zaak_is_assigned_to_me_from_the_werkvoorraad(
    zac: requests.Session, urls: dict[str, str], zac_zaak: Callable[..., JsonObject], zac_group: str
) -> None:
    """lijst/toekennen/mij makes the session's user the behandelaar; ZAC signals no one of a user's own action."""
    zaak = zac_zaak()
    expect_status(toekennen_mij(zac, urls["zac"], zaak, zac_group), HTTPStatus.OK)
    assert assignment(read_zaak(zac, urls["zac"], str(zaak["uuid"]))) == (zac_group, ADMIN.username)


@ZAC_TEAM
@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given the intake taak of a zaak in the test admin's group, without behandelaar
    When the admin assigns the taak to themselves from the takenlijst
    Then the taak has the admin as behandelaar
""")
def test_taak_is_assigned_to_me_from_the_werkvoorraad(
    zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject, zac_group: str
) -> None:
    """taken/lijst/toekennen/mij makes the session's user the taak's behandelaar and keeps its group."""
    taak = open_task(zac, urls["zac"], str(bpmn_zaak["uuid"]), INTAKE)
    expect_status(taak_toekennen_mij(zac, urls["zac"], taak), HTTPStatus.OK)
    assert assignment(read_taak(zac, urls["zac"], str(taak["id"]))) == (zac_group, ADMIN.username)


@ZAC_TEAM
@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given the intake taak of a zaak, assigned to the admin's group and the test admin
    When the behandelaar assigns the taak from the takenlijst to the group, without a behandelaar
    Then the taak has that group and no behandelaar
""")
def test_taak_verdeeld_to_a_group_alone_loses_its_behandelaar(
    zac: requests.Session, urls: dict[str, str], bpmn_zaak: JsonObject, zac_group: str
) -> None:
    """Verdelen without behandelaar releases an assigned taak (TaskService.assignTasks)."""
    taak = open_task(zac, urls["zac"], str(bpmn_zaak["uuid"]), INTAKE)
    toekennen_taak(zac, urls["zac"], taak, zac_group, ADMIN.username)
    expect_status(verdelen_taken(zac, urls["zac"], [taak], zac_group, None), HTTPStatus.NO_CONTENT)
    wait_until(
        lambda: assignment(read_taak(zac, urls["zac"], str(taak["id"]))) == (zac_group, None),
        timeout=LIST_TIMEOUT,
        description=f"taak {taak['id']} verdeeld to {zac_group}",
    )


@ZAC_TEAM
@pytest.mark.requires("pabc", "mailpit", "opennotificaties")
@pytest.mark.xdist_group("zac-signaleringen")
@pytest.mark.scenario("""
    Given the test admin wants a mail, and no dashboard signal, for taken put on their name
    And the intake taak of a zaak without behandelaar
    When the coordinator assigns the taak from the takenlijst to the admin's group and the admin
    Then the taak has that group and the admin
    And the admin gets a mail linking to the taak
""")
def test_taak_verdeeld_by_a_coordinator_mails_the_behandelaar(
    zac: requests.Session,
    zac_as: Callable[[str], requests.Session],
    urls: dict[str, str],
    bpmn_zaak: JsonObject,
    zac_group: str,
    signaleringen: Callable[..., None],
    mailpit: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """The coordinator's verdelen gives the taak its behandelaar, who gets TAAK_OP_NAAM by mail."""
    signaleringen(mail=True, TAAK_OP_NAAM=False)
    taak = open_task(zac, urls["zac"], str(bpmn_zaak["uuid"]), INTAKE)
    verdeeld = verdelen_taken(zac_as("coordinator"), urls["zac"], [taak], zac_group, ADMIN.username)
    expect_status(verdeeld, HTTPStatus.NO_CONTENT)
    wait_until(
        lambda: assignment(read_taak(zac, urls["zac"], str(taak["id"]))) == (zac_group, ADMIN.username),
        timeout=LIST_TIMEOUT,
        description=f"taak {taak['id']} verdeeld",
    )
    signalering_mail(mailpit, registry, ADMIN.username, f"/taken/{taak['id']}", timeout=LIST_TIMEOUT)


@ZAC_TEAM
@pytest.mark.requires("pabc")
@pytest.mark.scenario("""
    Given a group with the behandelaar role on the BPMN test zaaktype
    And a group with the behandelaar role on a zaaktype of another domain
    When the coordinator verdeelt a selection of zaken of one of those zaaktypen
    Then ZAC offers the group of that zaaktype
    When the selection holds zaken of both zaaktypen
    Then ZAC offers only the groups it offers for each zaaktype, so neither of those two
""")
def test_verdelen_offers_only_groups_authorised_for_every_selected_zaaktype(
    zac: requests.Session,
    podiumd_env: Environment,
    urls: dict[str, str],
    bpmn_zaaktype: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """ZAC's groups for verdelen are those PABC authorises as behandelaar for every selected zaaktype."""
    bpmn = str(bpmn_zaaktype["omschrijving"])
    eigen = make_role_group(podiumd_env, registry, "behandelaar")
    # The other domain's zaaktype has the group's name.
    ander = make_other_domain_group(podiumd_env, registry, "behandelaar")
    # Two zaaktypen: ZAC's call for a selection; estate groups with rights on every zaaktype are in each set.
    voor_bpmn = behandelaar_groups(zac, urls["zac"], bpmn, bpmn)
    voor_ander = behandelaar_groups(zac, urls["zac"], ander, ander)
    assert (eigen in voor_bpmn, ander in voor_ander) == (True, True)
    voor_beide = behandelaar_groups(zac, urls["zac"], bpmn, ander)
    assert (voor_beide, {eigen, ander} & voor_beide) == (voor_bpmn & voor_ander, set())
