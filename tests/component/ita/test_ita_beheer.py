"""ITA's functioneel beheerder: Alle contactverzoeken, and reopening a closed contactverzoek.

Ported from ITA's own Playwright suite (InterneTaakAfhandeling.EndToEndTest), as the API calls of its pages.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ITA_BEHEERDER
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.ita import overview
from podiumd_tests.ita import uuids
from podiumd_tests.kcc import kcc_login
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openklant import close_internetaak
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("ita", "openklant", "objecten", "keycloak")]

E2E = "upstream interne-taak-afhandeling/ITA InterneTaakAfhandeling.EndToEndTest"


@pytest.fixture(name="closed_taak")
def fixture_closed_taak(openklant: ApiClient, internetaak: JsonObject) -> JsonObject:
    """An internetaak set to verwerkt."""
    return close_internetaak(openklant, internetaak)


@pytest.fixture(name="ita_as")
def fixture_ita_as(
    page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> Callable[[KeycloakUser], requests.Session]:
    """An ITA session of a test user, logged in in the browser; each login replaces the browser's previous one."""

    def login(user: KeycloakUser) -> requests.Session:
        need_bootstrap(user.name)
        page.context.clear_cookies()
        return kcc_login(page, podiumd_env, "ita", user)

    return login


@pytest.mark.source(
    f"{E2E}/AlleContactverzoeken/AlleContactverzoekenAccessScenarios.cs",
    "A beheerder opens Alle contactverzoeken; a medewerker without the beheerder role is blocked.",
)
@pytest.mark.scenario("""
    Given the functioneel beheerder and the KCC medewerker of ITA
    When each opens Alle contactverzoeken in ITA
    Then ITA shows the list to the functioneel beheerder
    And refuses the KCC medewerker
""")
def test_only_the_beheerder_lists_all_contactverzoeken(
    ita_as: Callable[[KeycloakUser], requests.Session], urls: dict[str, str]
) -> None:
    """ITA's list of all internetaken answers the functioneel beheerder and refuses the KCC user."""
    alle = f"{urls['ita']}/api/internetaken"
    expect_status(ita_as(ITA_BEHEERDER).get(alle), HTTPStatus.OK)
    expect_status(ita_as(KCC).get(alle), *REFUSED)


@pytest.mark.source(
    f"{E2E}/Contactverzoek/ContactverzoekScenarios.cs",
    "Alle contactverzoeken lists an open contactverzoek; a closed one is no longer on it.",
)
@pytest.mark.scenario("""
    Given an open and a closed contactverzoek in Open Klant
    When the functioneel beheerder opens Alle contactverzoeken in ITA
    Then ITA lists the open contactverzoek
    And not the closed one
""")
def test_alle_contactverzoeken_lists_only_open_ones(
    ita_as: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    openklant: ApiClient,
    registry: ResourceRegistry,
    closed_taak: JsonObject,
) -> None:
    """ITA's list of all internetaken has the te_verwerken ones, not the verwerkt ones."""
    open_taak = make_internetaak(openklant, registry, make_klantcontact(openklant, registry), [])
    listed = set(uuids(overview(ita_as(ITA_BEHEERDER), f"{urls['ita']}/api/internetaken")))
    assert (open_taak["uuid"] in listed, closed_taak["uuid"] in listed) == (True, False)


@pytest.mark.source(
    f"{E2E}/Contactverzoek/HeropenContactverzoekScenarios.cs",
    "A beheerder reopens a closed contactverzoek with a reason; confirming without a reason is not possible.",
)
@pytest.mark.scenario("""
    Given a closed contactverzoek in Open Klant
    When the functioneel beheerder reopens it in ITA without a reason
    Then ITA refuses it
    And ITA refuses the KCC medewerker to reopen it
    When the functioneel beheerder reopens it with a reason
    Then the contactverzoek is te_verwerken again in Open Klant
""")
def test_beheerder_reopens_a_closed_contactverzoek(
    ita_as: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    openklant: ApiClient,
    closed_taak: JsonObject,
) -> None:
    """Without a reason the reopen is refused; with one the internetaak is open again and the KCC may not reopen."""
    heropen = f"{urls['ita']}/api/internetaken/{closed_taak['uuid']}/heropen"
    beheerder = ita_as(ITA_BEHEERDER)
    expect_status(beheerder.post(heropen, json={"reden": ""}), HTTPStatus.BAD_REQUEST)
    expect_status(ita_as(KCC).post(heropen, json={"reden": "podiumd-tests"}), *REFUSED)
    expect_status(beheerder.post(heropen, json={"reden": "podiumd-tests"}), HTTPStatus.OK)
    assert openklant.get(f"internetaken/{closed_taak['uuid']}")["status"] == "te_verwerken"
