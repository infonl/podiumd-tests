"""ITA as the klantcontactmedewerker: lists, claiming an internetaak and answering it with a klantcontact.

Ported from TA regression 77, 73 and interaction 74 and 180 (with a numeric nummer and the
current add-klantcontact body; the TA versions failed on both).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.kcc import kcc_login
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import klantcontact_body
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("ita", "openklant", "keycloak")]


@pytest.fixture(name="ita")
def fixture_ita(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """ITA in the KCC test user's session; ITA finds the user's Open Klant actor by e-mail."""
    need_bootstrap(KCC.name, "openklant-actor-kcc")
    return kcc_login(page, podiumd_env, "ita")


def get_list(ita: requests.Session, url: str) -> list[JsonObject]:
    """GET an ITA list; it must answer 200 with a JSON array."""
    response = expect_status(ita.get(url), HTTPStatus.OK)
    return entries(response.json())


def test_afdelingen_and_groepen_are_seeded_together(ita: requests.Session, urls: dict[str, str]) -> None:
    """Afdelingen and groepen both answer, and are both empty or both filled (TA reg-77)."""
    afdelingen = get_list(ita, urls["ita"] + "/api/afdelingen")
    groepen = get_list(ita, urls["ita"] + "/api/groepen")
    assert bool(afdelingen) == bool(groepen), f"{len(afdelingen)} afdelingen, {len(groepen)} groepen"


def test_claimed_internetaak_is_on_my_list(
    ita: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry
) -> None:
    """A claimed internetaak is assigned to the user's actor and on the user's list (TA int-74, reg-73)."""
    taak = make_internetaak(openklant, registry, make_klantcontact(openklant, registry), [])
    claim = ita.post(f"{urls['ita']}/api/internetaken/{taak['uuid']}/aan-mij-toewijzen", json={})
    expect_status(claim, HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.NO_CONTENT)
    assert entries(openklant.get(f"internetaken/{taak['uuid']}")["toegewezenAanActoren"])
    mine = get_list(ita, urls["ita"] + "/api/internetaken/aan-mij-toegewezen")
    assert taak["uuid"] in {str(t.get("uuid")) for t in mine}


def test_answering_an_internetaak_registers_a_klantcontact(
    ita: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry
) -> None:
    """Answering an internetaak with a contact registers that klantcontact in Open Klant (TA int-180)."""
    aanleiding = make_klantcontact(openklant, registry)
    taak = make_internetaak(openklant, registry, aanleiding, [])
    antwoord = klantcontact_body(registry, onderwerp=registry.tagged("ita-antwoord"), indicatieContactGelukt=False)
    body = {
        "interneTaakId": taak["uuid"],
        "aanleidinggevendKlantcontactUuid": aanleiding["uuid"],
        "klantcontactRequest": {k: v for k, v in antwoord.items() if k != "nummer"},
    }
    response = ita.post(urls["ita"] + "/api/klantcontacten/add-klantcontact", json=body)
    found = openklant.list("klantcontacten", {"onderwerp": str(antwoord["onderwerp"])})
    for klantcontact in found:
        registry.add(f"klantcontact {klantcontact['url']}", lambda url=str(klantcontact["url"]): openklant.delete(url))
    assert response.status_code in {HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.NO_CONTENT}, describe(response)
    assert [k["indicatieContactGelukt"] for k in found] == [False]
