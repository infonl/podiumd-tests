"""ZAC with run-tagged zaaktypen in its own catalogus: the zaakafhandelparameters list and the inrichtingscheck, which
ZAC computes for the zaaktypen of that catalogus only.

Tests run only where profile setting zac_catalogus_writes allows them to publish there.
"""

from __future__ import annotations

import dataclasses

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openzaak import today
from podiumd_tests.seed.zac_zaaktype import ZAC_TYPES
from podiumd_tests.seed.zac_zaaktype import publish_zac_zaaktype
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import clear_ztc_cache
from podiumd_tests.zac import configure_zaaktype
from podiumd_tests.zac import inrichtingscheck_problems
from podiumd_tests.zac import read_zaakafhandelparameters
from podiumd_tests.zac import user_groups

if TYPE_CHECKING:
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
