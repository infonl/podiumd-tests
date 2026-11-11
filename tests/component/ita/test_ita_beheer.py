"""ITA's functioneel beheerder: Alle contactverzoeken, and reopening a closed contactverzoek.

Ported from ITA's own Playwright suite (InterneTaakAfhandeling.EndToEndTest), as the API calls of its pages.
"""

from __future__ import annotations

import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import ITA_BEHEERDER
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.ita import make_eenheid
from podiumd_tests.ita import overview
from podiumd_tests.ita import uuids
from podiumd_tests.kcc import kcc_login
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
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


@pytest.mark.source(
    f"{E2E}/Kanaal/Kanaal.cs",
    "A beheerder adds, edits and deletes a kanaal; a duplicate name is refused; a KCC user cannot manage kanalen.",
)
@pytest.mark.scenario("""
    Given the functioneel beheerder is logged in to ITA
    When the beheerder adds a kanaal
    Then ITA lists it, and refuses a second kanaal with the same name
    When the beheerder renames it and then deletes it
    Then ITA lists the new name, and after the delete no longer finds it
    And the KCC medewerker may not add a kanaal
""")
def test_beheerder_manages_kanalen(
    ita_as: Callable[[KeycloakUser], requests.Session], urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """/api/kanaal: 201, 409 for a duplicate naam, 200 on PUT, 204 on DELETE, 404 after; refused to the KCC user."""
    kanalen, kanaal_url = f"{urls['ita']}/api/kanalen", f"{urls['ita']}/api/kanaal"
    kcc = ita_as(KCC)
    expect_status(kcc.post(kanaal_url, json={"naam": registry.tagged("kanaal-kcc")}), *REFUSED)
    beheerder = ita_as(ITA_BEHEERDER)
    naam = registry.tagged(f"kanaal-{secrets.token_hex(3)}")
    created = expect_status(beheerder.post(kanaal_url, json={"naam": naam}), HTTPStatus.CREATED).json()
    one = f"{kanaal_url}/{created['id']}"
    registry.add(f"kanaal {naam}", lambda: beheerder.delete(one))

    def namen() -> list[str]:
        return [str(kanaal.get("naam")) for kanaal in get_entries(beheerder, kanalen)]

    assert naam in namen()
    expect_status(beheerder.post(kanaal_url, json={"naam": naam}), HTTPStatus.CONFLICT)
    expect_status(beheerder.put(one, json={"naam": f"{naam}-nieuw"}), HTTPStatus.OK)
    assert f"{naam}-nieuw" in namen()
    assert naam not in namen()
    expect_status(beheerder.delete(one), HTTPStatus.NO_CONTENT)
    expect_status(beheerder.get(one), HTTPStatus.NOT_FOUND)


@pytest.mark.parametrize("soort", ["Afdeling", "Groep"])
@pytest.mark.source(
    f"{E2E}/Contactverzoek/ContactverzoekDoorsturenGroepsmailboxScenarios.cs",
    "The forward form knows which afdelingen and groepen have a groepsmailbox.",
)
@pytest.mark.scenario("""
    Given an afdeling or groep with a groepsmailbox and one without
    When the KCC medewerker opens ITA's forward form
    Then ITA marks the first as having a groepsmailbox and the second not
""")
def test_afdelingen_and_groepen_tell_their_groepsmailbox(  # fixtures
    ita_as: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    podiumd_env: Environment,
    objecten: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
    soort: str,
) -> None:
    """GET /api/afdelingen and /api/groepen: heeftGroepsmailbox follows the object's e-mail address."""
    met, zonder = (
        make_eenheid(podiumd_env, objecten, openklant, registry, soort, with_mailbox=mailbox)
        for mailbox in (True, False)
    )
    listed = get_entries(ita_as(KCC), f"{urls['ita']}/api/{soort.lower()}en")
    found = {str(item.get("identificatie")): item.get("heeftGroepsmailbox") for item in listed}
    assert (found.get(met), found.get(zonder)) == (True, False)
