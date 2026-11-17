"""ZAC with run-tagged zaaktypen in its own catalogus: the zaakafhandelparameters list and the inrichtingscheck, which
ZAC computes for the zaaktypen of that catalogus only.

Tests run only where profile setting zac_catalogus_writes allows them to publish there.
"""

from __future__ import annotations

import dataclasses

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import ZacBpmnProcess
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openzaak import today
from podiumd_tests.seed.zac_zaaktype import ZAC_TYPES
from podiumd_tests.seed.zac_zaaktype import publish_zac_zaaktype
from podiumd_tests.wait import wait_until
from podiumd_tests.workloads import is_older_than
from podiumd_tests.workloads import skip_older_than
from podiumd_tests.zac import clear_ztc_cache
from podiumd_tests.zac import configure_zaaktype
from podiumd_tests.zac import inrichtingscheck_problems
from podiumd_tests.zac import read_zaakafhandelparameters
from podiumd_tests.zac import user_groups

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    # A throwaway zaaktype is deleted with a Django snippet.
    pytest.mark.requires("zac", "openzaak", "keycloak", "cluster"),
    pytest.mark.xdist_group("zac-catalogus"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, beheer-zaps).",
    ),
]

# Seconds ZAC takes to list a zaaktype Open Zaak published: its zaaktype notificatie clears ZAC's cache.
LIST_TIMEOUT = 60


def _listed(zac: requests.Session, zac_url: str, zaaktype: JsonObject) -> JsonObject | None:
    """Return ZAC's entry of the zaaktype version in its list of zaakafhandelparameters; None when not listed."""
    found = get_entries(zac, f"{zac_url}/rest/zaakafhandelparameters")
    return next((item for item in found if section(item, "zaaktype").get("uuid") == uuid_of(zaaktype["url"])), None)


@pytest.mark.parametrize("archiefactietermijn", [True, False], ids=["met-archieftermijn", "zonder-archieftermijn"])
@pytest.mark.scenario("""
    Given ZAC's own catalogus in Open Zaak
    When a new zaaktype is published there, with or without archieftermijn on its resultaattype
    Then the beheerder finds it in ZAC's list of zaakafhandelparameters, not configured and without creatiedatum
    And its zaakafhandelparameters offer the afzenders gemeente and medewerker
    When the beheerder saves them
    Then the list shows today as their creatiedatum
""")
def test_new_zaaktype_in_zacs_catalogus_is_listed(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    eigen_catalogus: JsonObject,
    registry: ResourceRegistry,
    *,
    archiefactietermijn: bool,
) -> None:
    """GET zaakafhandelparameters lists a zaaktype published in ZAC's catalogus, without a cache clear."""
    types = dataclasses.replace(ZAC_TYPES, archiefactietermijn=archiefactietermijn)
    zaaktype = publish_zac_zaaktype(
        podiumd_env, openzaak, registry, test_zaaktype, types=types, catalogus=eigen_catalogus["url"]
    )
    zac_url, uuid = urls["zac"], uuid_of(zaaktype["url"])
    listed = wait_until(
        lambda: _listed(zac, zac_url, zaaktype), timeout=LIST_TIMEOUT, description=f"{zaaktype['omschrijving']} in ZAC"
    )
    assert (listed.get("id"), listed.get("creatiedatum"), listed.get("valide")) == (None, None, False)
    found = read_zaakafhandelparameters(zac, zac_url, uuid)
    assert {str(afzender.get("mail")) for afzender in entries(found.get("zaakAfzenders"))} == {"GEMEENTE", "MEDEWERKER"}
    configure_zaaktype(zac, zac_url, uuid, user_groups(zac, zac_url)[0])
    configured = _listed(zac, zac_url, zaaktype) or {}
    assert str(configured.get("creatiedatum")).startswith(today())


# What a broken zaaktype lacks, as ZAC's inrichtingscheck reports it (inrichtingscheck_problems), and its types.
BROKEN = {
    "aantalBehandelaarroltypen=0": dataclasses.replace(ZAC_TYPES, roltypen=(("Initiator", "initiator"),)),
    "aantalInitiatorroltypen=0": dataclasses.replace(ZAC_TYPES, roltypen=(("Behandelaar", "behandelaar"),)),
    "statustypeAanvullendeInformatieVereist": dataclasses.replace(
        ZAC_TYPES, statustypen=("Intake", "In behandeling", "Afgerond")
    ),
}


@pytest.mark.scenario("""
    Given ZAC's own catalogus has a zaaktype with every statustype and roltype ZAC needs
    And one without roltype Behandelaar, one without roltype Initiator
    And one without statustype Wacht op aanvullende informatie
    When the beheerder runs ZAC's inrichtingscheck
    Then it reports each broken zaaktype for what it lacks, besides what the complete one lacks
    And it finds the communicatiekanaal E-formulier, which it checks once, not per zaaktype
""")
def test_inrichtingscheck_rejects_a_zaaktype_without_behandelaar_initiator_or_aanvullende_informatie(
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    eigen_catalogus: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """/rest/health-check/zaaktypes finds a missing Behandelaar, Initiator or Wacht op aanvullende informatie."""
    zaaktypen = {
        lacks: publish_zac_zaaktype(
            podiumd_env, openzaak, registry, test_zaaktype, types=types, catalogus=eigen_catalogus["url"]
        )["omschrijving"]
        for lacks, types in {"": ZAC_TYPES, **BROKEN}.items()
    }
    clear_ztc_cache(zac, urls["zac"])
    checks = {
        section(check, "zaaktype").get("omschrijving"): set(inrichtingscheck_problems(check))
        for check in get_entries(zac, f"{urls['zac']}/rest/health-check/zaaktypes")
    }
    complete = checks[zaaktypen[""]]
    assert {lacks: checks[omschrijving] - complete for lacks, omschrijving in zaaktypen.items()} == {
        lacks: {lacks} - {""} for lacks in zaaktypen
    }
    eformulier = zac.get(f"{urls['zac']}/rest/health-check/bestaat-communicatiekanaal-eformulier")
    assert expect_status(eformulier, HTTPStatus.OK).json() is True


# ZAC reports a resultaattype whose brondatum it cannot derive from this release on (PZ-13306).
REPORTS_UNSUPPORTED_BRONDATUM = (5, 12, 0)


@pytest.mark.source(
    "PZW Sprint 83 PZ-13306",
    "The inrichtingscheck shows an error for a zaaktype with afhandelwijze 'Zaakobject' or 'Ander datumkenmerk'.",
)
@pytest.mark.scenario("""
    Given ZAC's own catalogus has a zaaktype with resultaattypen whose brondatum comes from a zaakobject
    And one from another datumkenmerk, and one from the afhandeling of the zaak
    When the beheerder runs ZAC's inrichtingscheck
    Then it names the zaakobject and ander datumkenmerk resultaattypen as an afhandelwijze ZAC does not support
""")
def test_inrichtingscheck_names_resultaattypen_with_an_unsupported_brondatum(  # the catalogus
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    eigen_catalogus: JsonObject,
    registry: ResourceRegistry,
) -> None:
    """resultaattypesMetNietOndersteundeBrondatum lists the resultaattypen with afleidingswijze zaakobject or
    ander_datumkenmerk."""
    skip_older_than(podiumd_env, "zac", REPORTS_UNSUPPORTED_BRONDATUM, "no check of the brondatum afleidingswijze")
    types = dataclasses.replace(ZAC_TYPES, afleidingswijzen=("zaakobject", "ander_datumkenmerk", "afgehandeld"))
    zaaktype = publish_zac_zaaktype(
        podiumd_env, openzaak, registry, test_zaaktype, types=types, catalogus=eigen_catalogus["url"]
    )
    clear_ztc_cache(zac, urls["zac"])
    checks = get_entries(zac, f"{urls['zac']}/rest/health-check/zaaktypes")
    mine = [c for c in checks if section(c, "zaaktype").get("omschrijving") == zaaktype["omschrijving"]]
    assert [sorted(strings(c.get("resultaattypesMetNietOndersteundeBrondatum"))) for c in mine] == [
        ["ander_datumkenmerk", "zaakobject"]
    ]
    assert [c.get("valide") for c in mine] == [False]


# ZAC leaves zaaktypen bound to BPMN out of its inrichtingscheck from this release on (PZ-11837).
SKIPS_BPMN_ZAAKTYPEN = (5, 11, 0)


@pytest.mark.source(
    "PZW Sprint 82 PZ-11837", "BPMN zaaktypen are no longer shown in or checked by the inrichtingscheck."
)
@pytest.mark.scenario("""
    Given ZAC's own catalogus has a zaaktype whose zaken ZAC handles with a BPMN process
    When the beheerder runs ZAC's inrichtingscheck
    Then from ZAC 5.11 the BPMN zaaktype is not in it, before 5.11 it is
""")
def test_inrichtingscheck_leaves_out_bpmn_zaaktypen(  # the catalogus and the BPMN process
    podiumd_env: Environment,
    zac: requests.Session,
    urls: dict[str, str],
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    eigen_catalogus: JsonObject,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> None:
    """ZAC's inrichtingscheck has no entry for a zaaktype bound to BPMN from ZAC 5.11 on."""
    need_bootstrap("zac-bpmn-process")
    zaaktype = publish_zac_zaaktype(podiumd_env, openzaak, registry, test_zaaktype, catalogus=eigen_catalogus["url"])
    ZacBpmnProcess(ADMIN).link_zaaktype(zac, urls["zac"], zaaktype)
    clear_ztc_cache(zac, urls["zac"])
    checks = get_entries(zac, f"{urls['zac']}/rest/health-check/zaaktypes")
    listed = {section(c, "zaaktype").get("uuid") for c in checks}
    assert (uuid_of(zaaktype["url"]) in listed) is is_older_than(podiumd_env, "zac", SKIPS_BPMN_ZAAKTYPEN)
