"""KISS as the klantcontactmedewerker: a session with the KCC role, and klantcontacten through KISS.

Ported from TA smoke 06 and 113, and regression 12 and 100.
"""

from __future__ import annotations

import json

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import KVK_TEST_NUMMER
from podiumd_tests.bootstrap.kiss import KANALEN
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kcc import KISS_KLANTCONTACTEN
from podiumd_tests.kcc import kcc_login
from podiumd_tests.kcc import kiss_register
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.seed.openklant import klantcontact_body

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.core, pytest.mark.requires("kiss", "keycloak")]


@pytest.fixture(name="kiss")
def fixture_kiss(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """KISS in the KCC test user's session."""
    need_bootstrap(KCC.name)
    return kcc_login(page, podiumd_env, "kiss")


@pytest.mark.tc("KI-002")
def test_kcc_user_is_a_klantcontactmedewerker(kiss: requests.Session, urls: dict[str, str]) -> None:
    """KISS knows the logged-in user as a klantcontactmedewerker (TA smoke 113)."""
    me = expect_status(kiss.get(urls["kiss"] + "/api/me"), HTTPStatus.OK).json()
    assert me["isLoggedIn"]
    assert me["isKcm"]


@pytest.mark.tc("KI-001")
def test_kiss_renders_for_the_kcc_user(kiss: requests.Session, page: Page, urls: dict[str, str]) -> None:
    """After the login KISS's single-page app renders its search and navigation (TA smoke 06, reg-100)."""
    del kiss  # logs the page in
    page.goto(urls["kiss"] + "/")
    expect(page.get_by_role("banner").get_by_role("button", name="Zoeken")).to_be_visible()
    expect(page.get_by_role("link", name="Uitloggen")).to_be_visible()


def test_klantcontact_through_kiss(
    kiss: requests.Session, urls: dict[str, str], openklant: ApiClient, registry: ResourceRegistry
) -> None:
    """A klantcontact registered through KISS lands in Open Klant (TA reg-12).

    KISS does not delete klantcontacten (DELETE answers 405); cleanup goes to Open Klant.
    """
    body = klantcontact_body(registry, onderwerp=registry.tagged("kiss-klantcontact"))
    response = kiss.post(urls["kiss"] + KISS_KLANTCONTACTEN, json=body, headers=kiss_register(kiss, urls["kiss"]))
    created = expect_status(response, HTTPStatus.CREATED).json()
    registry.add(f"klantcontact {created['url']}", lambda: openklant.delete(str(created["url"])))
    assert openklant.get(f"klantcontacten/{created['uuid']}")["onderwerp"] == body["onderwerp"]


@pytest.mark.tc("KI-007")
def test_person_unknown_to_kiss_is_found_in_the_brp(kiss: requests.Session, urls: dict[str, str]) -> None:
    """KISS finds a person by BSN through its Haal Centraal BRP proxy.

    KISS rewrites the request body and keeps its Content-Length, so the JSON must be compact, as
    KISS's own frontend sends it (PLAN §13).
    """
    query = {"type": "RaadpleegMetBurgerservicenummer", "burgerservicenummer": [EREBOS], "fields": ["naam"]}
    found = kiss.post(
        urls["kiss"] + "/api/haalcentraal/brp/personen",
        data=json.dumps(query, separators=(",", ":")),
        headers={"Content-Type": "application/json"},
    )
    personen = entries(expect_status(found, HTTPStatus.OK).json()["personen"])
    assert [section(p, "naam").get("voornamen") for p in personen] == ["Erebos"]


@pytest.mark.tc("KI-013")
def test_company_unknown_to_kiss_is_found_in_the_kvk(kiss: requests.Session, urls: dict[str, str]) -> None:
    """KISS finds a company by KvK number through its KvK proxy."""
    found = expect_status(kiss.get(urls["kiss"] + "/api/kvk/v2/zoeken", params={"kvkNummer": KVK_TEST_NUMMER}), 200)
    assert KVK_TEST_NUMMER in {str(r.get("kvkNummer")) for r in entries(found.json()["resultaten"])}


@pytest.mark.tc("KI-053", "KI-054", "KI-055")
@pytest.mark.parametrize("kanaal", KANALEN)
def test_klantcontact_keeps_the_kanaal_chosen_in_kiss(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    kiss: requests.Session,
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
    kanaal: str,
) -> None:
    """A klantcontact registered through KISS on a kanaal KISS offers lands in Open Klant on exactly that kanaal."""
    need_bootstrap("kiss-kanalen")
    offered = {str(k["naam"]) for k in get_entries(kiss, urls["kiss"] + "/api/KanalenContactmomentKeuzelijst")}
    if kanaal not in offered:
        pytest.skip(
            f"KISS offers no kanaal {kanaal}: add it in KISS (Beheer, Kanalen) or set profile setting kiss_kanalen"
        )
    body = klantcontact_body(registry, kanaal=kanaal, onderwerp=registry.tagged(f"kanaal-{kanaal.lower()}"))
    response = kiss.post(urls["kiss"] + KISS_KLANTCONTACTEN, json=body, headers=kiss_register(kiss, urls["kiss"]))
    created = expect_status(response, HTTPStatus.CREATED).json()
    registry.add(f"klantcontact {created['url']}", lambda: openklant.delete(str(created["url"])))
    assert openklant.get(f"klantcontacten/{created['uuid']}")["kanaal"] == kanaal
